import logging, datetime
import utils.gpu as gpu
from model.build_model import Build_Model
from tqdm import tqdm
import torch
import time
import argparse
from eval.evaluator import *
from utils.tools import *
from config import cfg
from config import update_config
from utils.log import Logger
from utils.utils import init_seed
from eval_coco import *
from eval.cocoapi_evaluator import COCOAPIEvaluator

class Naive_Test_Dataset(Dataset):
    def __init__(self, cfg, test_images):
        super().__init__()
        self.cfg = cfg
        self.img_size = cfg.VAL.TEST_IMG_SIZE
        self.imgs = [filename.replace("data/","/data/ECP_origin").replace("images","img") for filename in test_images]

    def __len___(self):
        return len(self.imgs)   

    def __getitem(self, index):
        img_path = self.imgs[index]
        img = cv2.imread(os.path.join(cfg.DATA_PATH, img_path))
        img, info_img = preprocess(img, self.img_size, jitter=0,
                                   random_placing=0)
        img = np.transpose(img / 255., (2, 0, 1))
        return img_path, img, info_img   
        
class LAMR_Tester(object):
    id_map = ["pedestrian"]
    def __init__(self, log_dir, test_images):
        init_seeds(0)
        self.device = gpu.select_device()
        self.log_dir = log_dir
        self.yolov4 = Build_Model(weight_path=None, resume=False)
        self.yolov4 = self.yolov4.to(self.device)
        self.dataset = Naive_Test_Dataset(test_images)
        self.dataloader = torch.utils.data.DataLoader(
            self.dataset, batch_size=cfg.VAL.BATCH_SIZE, shuffle=False, pin_memory=True,num_workers=cfg.VAL.NUMBER_WORKERS)
        self.__load_best_weights()

    def __load_best_weights(self):
        best_weight = os.path.join(log_dir,"checkpoints", "best.pt")
        chkpt = torch.load(best_weight, map_location=self.device)
        self.yolov4.load_state_dict(chkpt)
        del chkpt

    def test(self):
        logger.info(self.yolov4)
        self.yolov4.eval()
        Tensor = torch.cuda.FloatTensor if cuda else torch.FloatTensor
        results_path = os.path.join("/data","mock_detections","day","test")
        if not os.path.exists(results_path):
            os.makedirs(results_path)
        for i,(img_path, img, info_img) in tqdm(enumerate(self.dataloader),desc="Test to ECP... ", unit="imgs", total=len(self.dataloader)):
            with torch.no_grad():
                img = Variable(img.type(Tensor))
                _,outputs = model(img)
                outputs=outputs.unsqueeze(0)
                outputs = postprocess(
                    outputs, self.class_num, self.confthre, self.nmsthre)
                if outputs[0] is None:
                    continue
                outputs = outputs[0].cpu().data
            data_dict = {
                "tags": []
                "imageheight":img.shape[1]
                "imagewidth": img.shape[2]
                "children": []
                "identity": "frame"
            }
            
            for output in outputs:
                x1 = float(output[0])
                y1 = float(output[1])
                x2 = float(output[2])
                y2 = float(output[3])
                box = yolobox2label((y1, x1, y2, x2), info_img)

                A = {"tags": ["occluded>10"],
                     "children": [],
                     "identity": self.id_map[int(output[6])],
                     "x0": box[0],
                     "y0": box[1],
                     "x1": box[2],
                     "y1": box[3]
                     } # ECP json format
                data_dict["children"].append(A)
            city_name = os.path.basename(os.path.dirname(img_path))
            os.makedirs(os.path.join(results_path,city_name),exist_ok=True)
            result_json_path = os.path.join(results_path,city_name,os.path.basename(img_path).replace("png","json"))
            with open(result_json_path) as json_fh:
                json.dump(data_dict,json_fh,indent=4)

        
def init_logger(log_dir=None, log_level=logging.INFO, mode='w', stdout=True):
    """
    log_dir: 日志文件的文件夹路径
    mode: 'a', append; 'w', 覆盖原文件写入.
    """
    def get_date_str():
        now = datetime.datetime.now()
        return now.strftime('%Y-%m-%d_%H-%M-%S')

    fmt = '%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s: %(message)s'
    log_file = 'test_log_' + get_date_str() + '.txt'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, log_file)
    # 此处不能使用logging输出
    print('log file path:' + log_file)

    logging.basicConfig(level=logging.DEBUG,
                        format=fmt,
                        filename=log_file,
                        filemode=mode)

    if stdout:
        console = logging.StreamHandler(stream=sys.stdout)
        console.setLevel(log_level)
        formatter = logging.Formatter(fmt)
        console.setFormatter(formatter)
        logging.getLogger('').addHandler(console)

    return logging    

def getArgs():
    parser = argparse.ArgumentParser(description='Train the Model on images and target masks',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--config_file', type=str, default="experiment/demo.yaml", help="yaml configuration file")
    parser.add_argument("--split_file",type=str, default=None, help="split_file")
    parser.add_argument("--output_path", type=str, default="data/", help="test output with original ECP format")
    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = getArgs()
    # import config file and save it to log
    update_config(cfg, args)
    log_dir = os.path.join("log",os.path.basename(args.config_file)[:-5])
    logger = init_logger(log_dir=log_dir)
    logger.debug(cfg)
    with open(args.split_file,"r") as f:
        split_fh = json.load(f)
        test_images_list = split_fh["test"]
    Tester(log_dir,test_image_list).test()
