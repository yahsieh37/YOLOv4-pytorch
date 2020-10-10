import os
import numpy as np

import torch
from torch.utils.data import Dataset
import cv2
from pycocotools.coco import COCO
from dataset import Build_VAL_Dataset

from utils.utils import *


class COCODataset(Dataset):
    """
    COCO dataset class.
    """
    def __init__(self, lable_path, cfg):
        """
        COCO dataset initialization. Annotation data are read into memory by COCO API.
        Args:
            model_type (str): model name specified in config file
            data_dir (str): dataset root directory
            json_file (str): COCO json file name
            name (str): COCO data name (e.g. 'train2017' or 'val2017')
            img_size (int): target image size after pre-processing
            min_size (int): bounding boxes smaller than this are ignored
            debug (bool): if True, only one data id is selected from the dataset
        """
        self.model_type = model_type
        
        self.coco = COCO()
        self.val_dataset = data.Build_VAL_Dataset(cfg)
        self.val_loader = DataLoader(val_dataset, batch_size=cfg.VAL.BATCH_SIZE, shuffle=True, num_workers=8,
                            pin_memory=True, drop_last=True, collate_fn=val_collate)
        self.coco = convert_to_coco_api(bbox_fmt='coco')
        self.coco.createIndex()
        
        self.ids = self.coco.getImgIds()
        if debug:
            self.ids = self.ids[1:2]
            print("debug mode...", self.ids)
        self.class_ids = sorted(self.coco.getCatIds())
        self.name = name
        self.max_labels = 50
        self.img_size = cfg.VAL.TEST_IMG_SIZE
        self.min_size = 1
        f = open(lable_path, 'r', encoding='utf-8')
        for line in f.readlines():
            data = line.rstrip().split(" ")
            truth[data[0]] = []
            if len(data) > 1:
                for i in data[1:]:
                    truth[data[0]].append([int(float(j)) for j in i.split(',')])

        self.truth = truth
        self.imgs = list(self.truth.keys())

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, index):
        """
        One image / label pair for the given index is picked up \
        and pre-processed.
        Args:
            index (int): data index
        Returns:
            img (numpy.ndarray): pre-processed image
            padded_labels (torch.Tensor): pre-processed label data. \
                The shape is :math:`[self.max_labels, 5]`. \
                each label consists of [class, xc, yc, w, h]:
                    class (float): class index.
                    xc, yc (float) : center of bbox whose values range from 0 to 1.
                    w, h (float) : size of bbox whose values range from 0 to 1.
            info_img : tuple of h, w, nh, nw, dx, dy.
                h, w (int): original shape of the image
                nh, nw (int): shape of the resized image without padding
                dx, dy (int): pad size
            id_ (int): same as the input index. Used for evaluation.
        """
        # id_ = self.ids[index]
        id_ = int(os.path.basename(img_path).split(".")[0])
        # anno_ids = self.coco.getAnnIds(imgIds=[int(id_)], iscrowd=None)
        # annotations = self.coco.loadAnns(anno_ids)

        # lrflip = False
        # if np.random.rand() > 0.5 and self.lrflip == True:
        #     lrflip = True

        # load image and preprocess
        # img_file = os.path.join(self.data_dir, self.name,
        #                         '{:012}'.format(id_) + '.jpg')
        img_path = self.imgs[index]
        bboxes_with_cls_id = np.array(self.truth.get(img_path), dtype=np.float)
        boxes = bboxes_with_cls_id[...,:4]
        boxes[..., 2:] = boxes[..., 2:] - boxes[..., :2]  # box width, box height
        img = cv2.imread(os.path.join(self.cfg.dataset_dir, img_path))

        # img = cv2.imread(img_file)

        # if self.json_file == 'instances_val5k.json' and img is None:
        #     img_file = os.path.join(self.data_dir, 'train2017',
        #                             '{:012}'.format(id_) + '.jpg')
        #     img = cv2.imread(img_file)
        # assert img is not None

        img, info_img = preprocess(img, self.img_size, jitter=self.jitter,
                                   random_placing=self.random_placing)


        img = np.transpose(img / 255., (2, 0, 1))

        # if lrflip:
        #     img = np.flip(img, axis=2).copy()

        # load labels
        labels = []
        for box in boxes:
            if box[2] > self.min_size and box[3] > self.min_size:
                labels.append(box)

        padded_labels = np.zeros((self.max_labels, 5))
        if len(labels) > 0:
            labels = np.stack(labels)
            labels = label2yolobox(labels, info_img, self.img_size, lrflip)
            padded_labels[range(len(labels))[:self.max_labels]
                          ] = labels[:self.max_labels]
        padded_labels = torch.from_numpy(padded_labels)

        return img, padded_labels, info_img, id_

    def convert_to_coco_api(self, bbox_fmt='voc'):
        """
        """
        print("in function convert_to_coco_api...")
        coco = COCO()
        # annotation IDs need to start at 1, not 0, see torchvision issue #1530
        ann_id = 1
        dataset = {'images': [], 'categories': [], 'annotations': []}
        categories = set()
        for img_idx in range(len(self.val_loader)):
            # find better way to get target
            # targets = ds.get_annotations(img_idx)
            img, targets = self.val_loader[img_idx]
            image_id = targets["image_id"].item()
            img_dict = {}
            img_dict['id'] = image_id
            img_dict['height'] = img.shape[-2]
            img_dict['width'] = img.shape[-1]
            dataset['images'].append(img_dict)
            bboxes = targets["boxes"]
            # to coco format: xmin, ymin, w, h
            if bbox_fmt.lower() == "voc":  # xmin, ymin, xmax, ymax
                bboxes[:, 2:] -= bboxes[:, :2]
            elif bbox_fmt.lower() == "yolo":  # xcen, ycen, w, h
                bboxes[:, :2] = bboxes[:, :2] - bboxes[:, 2:]/2
            elif bbox_fmt.lower() == "coco":
                pass
            else:
                raise ValueError(f"bounding box format {bbox_fmt} not supported!")
            
            bboxes = bboxes.tolist()
            labels = targets['labels'].tolist()
            areas = targets['area'].tolist()
            iscrowd = targets['iscrowd'].tolist()
            if 'masks' in targets:
                masks = targets['masks']
                # make masks Fortran contiguous for coco_mask
                masks = masks.permute(0, 2, 1).contiguous().permute(0, 2, 1)
            if 'keypoints' in targets:
                keypoints = targets['keypoints']
                keypoints = keypoints.reshape(keypoints.shape[0], -1).tolist()
            num_objs = len(bboxes)
            for i in range(num_objs):
                ann = {}
                ann['image_id'] = image_id
                ann['bbox'] = bboxes[i]
                ann['category_id'] = labels[i]
                categories.add(labels[i])
                ann['area'] = areas[i]
                ann['iscrowd'] = iscrowd[i]
                ann['id'] = ann_id
                if 'masks' in targets:
                    ann["segmentation"] = coco_mask.encode(masks[i].numpy())
                if 'keypoints' in targets:
                    ann['keypoints'] = keypoints[i]
                    ann['num_keypoints'] = sum(k != 0 for k in keypoints[i][2::3])
                dataset['annotations'].append(ann)
                ann_id += 1
        dataset['categories'] = [{'id': i} for i in sorted(categories)]
        coco_ds.dataset = dataset
        coco_ds.createIndex()
        return coco_ds