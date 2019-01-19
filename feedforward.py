import argparse
import os
import glob
import torchvision.transforms as transforms
from torch.autograd import Variable
import torch
import cv2
import numpy as np
from networks import cruzhack_forward
import utils.util as util
import utils.cruzhack_utils as face
import pickle
import calendar
import time
import random

class feedFoward:
    def __init__(self, pathG, pathD):
        # load pre-trained generator here
        self._modelG = cruzhack_forward.generatorFoward(conv_dim=64, c_dim=17, repeat_num=6)
        self._modelG.load_state_dict(torch.load(pathG, map_location='cpu'))
        self._modelG.eval()
        self._transform = transforms.Compose([transforms.ToTensor(),
                                              transforms.Normalize(mean=[0.5, 0.5, 0.5],
                                                                   std=[0.5, 0.5, 0.5])
                                              ])
        #load pre-trained discriminator here
        self._modelD = cruzhack_forward.Discriminator(image_size=128, conv_dim=64, c_dim=17, repeat_num=6)
        self._modelD.load_state_dict(torch.load(pathD, map_location='cpu'))
        self._modelD.eval()

    def Foward(self, face, desired_expression):
        # transform face by normalizing 
        face = torch.unsqueeze(self._transform(face), 0).float()
        desired_expression = torch.unsqueeze(torch.from_numpy(desired_expression/5.0), 0).float() # set up desired expression

        color, mask = self._modelG.forward(face, desired_expression)
        # calculate result
        masked_result = mask * face + (1.0 - mask) * color

        img = self.convertToimg(masked_result)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)# convert to OpenCV color BGR

        maskA = mask.detach().numpy()[0]
        maskA = np.transpose(maskA, (1,2,0))

        return img, maskA

    def FindAU(self, face):
        # transform face by normalizing 
        face = torch.unsqueeze(self._transform(face), 0).float()
        out_real, out_aux = self._modelD.forward(face)
        return out_real, out_aux
    
    def convertToimg(self, tensor):
        tensor = tensor.cpu().float()
        img = tensor.detach().numpy()[0]
        img = img*0.5+0.5 # reverse transform
        img = np.transpose(img, (1, 2, 0))
        return img*254.0

def find_epoch(model_path, load_epoch_num):
    if os.path.exists(model_path):
        if load_epoch_num == -1:
            epoch_num = 0
            for file in os.listdir(model_path):
                if file.startswith("net_epoch_"):
                    epoch_num = max(epoch_num, int(file.split('_')[2]))
        else:
            found = False
            for file in os.listdir(model_path):
                if file.startswith("net_epoch_"):
                    found = int(file.split('_')[2]) == load_epoch_num
                    if found: break
            assert found, 'Model for epoch %i not found' % load_epoch_num
            epoch_num = load_epoch_num
    else:
        assert load_epoch_num < 1, 'Model for epoch %i not found' % load_epoch_num
        epoch_num = 0

    return epoch_num

# =========================================================== #
# below, the main(), is a demo for how to use the feedforward #
# =========================================================== #
def main():
    parser = argparse.ArgumentParser(description='easy for input parameters')
    parser.add_argument('--img_path', type=str, 
                        default='/Users/xyli1905/Projects/Datasets/imgs_178/000009.png', 
                        help='path to the test image')
    parser.add_argument('--model_path', type=str, default='./checkpoints/model_align/', 
                        help='path to the pretrained model')
    parser.add_argument('--load_epoch', type=int, default=-1, help='specify the model to be loaded')

    parser.add_argument('--AU', type=str, default = './dataset/aus_openface.pkl', 
                        help = 'loading pre-processing AU')

    arg = parser.parse_args()

    AU_file = open(arg.AU, 'rb')
    conds = pickle.load(AU_file)

    image_name = arg.img_path.split('.')[-2]
    print(image_name)
    image_name = image_name.split('/')[-1]

    # use any original image as you want and clip it
    img_raw = cv2.imread(arg.img_path)
    img_raw = cv2.resize(img_raw,(0,0), fx=1, fy=1)
    img = cv2.cvtColor(img_raw, cv2.COLOR_BGR2RGB)

    real_face, face_origin_pos = face.face_crop_and_align(img)

    # load pretrained GANimation model and run
    epoch_num = find_epoch(arg.model_path, arg.load_epoch)
    load_filename_generator = 'net_epoch_%s_id_G.pth' % (epoch_num)
    load_filename_discriminator = 'net_epoch_%s_id_D.pth' % (epoch_num)
    pathG = os.path.join(arg.model_path, load_filename_generator)
    pathD = os.path.join(arg.model_path, load_filename_discriminator)

    convertor = feedFoward(pathG, pathD)

    # set expression
    expressions = np.ndarray((5,17), dtype = np.float)

    # define the target AU, for test use only
    target_AU = np.array([0.25, 0.11, 0.2 , 0.16, 1.92, 1.03, 0.3 , 2.15, 2.88, 1.61, 0.03, 0.09, 0.16, 0.11, 2.25, 0.37, 0.05], dtype = np.float)

    # find original AU of input image using discrinator of GANimation, for test use only
    out_real, out_aux = convertor.FindAU(real_face) # out_aux is the AU value from D 
    original_AU = out_aux.data.numpy()

    # interpolate between original_AU and the target_AU, for test only
    c = (original_AU - target_AU)/4
    for i in range(5):
       expressions[i] = c * i + target_AU

    # run model for above expressions
    result = np.zeros((1, img_raw.shape[1]*4, 3))
    for i in range(5):
        processed_face, maskA = convertor.Foward(real_face, expressions[i])
        new_img, mask, rotate, new_maskA = face.face_place_back(img_raw, processed_face, face_origin_pos, 
                                                                maskA_test=True, maskA = maskA)

        # handle maskA to image for dispalying
        maskA_t = np.expand_dims(new_maskA, axis=2)
        maskA_t = (maskA_t*254.0).astype(np.uint8)
        maskA_t = np.repeat(maskA_t, 3, axis=-1)

        # wrap up results
        current_result = np.hstack((img_raw, rotate, maskA_t, new_img))
        result = np.vstack((result, current_result))
        #print(np.shape(processed_face), np.shape(maskA), maskA.dtype)

    result  = cv2.resize(result,(0,0), fx=0.5, fy=0.5)

    timestamp = calendar.timegm(time.gmtime())
    image_out_name = "./results/processedface_"+image_name+"-"+str(timestamp)+".jpg"
    cv2.imwrite(image_out_name, result)
    print("Processed image saved as %s" % image_out_name)
    #cv2.imshow('result', result/254.0)
    #cv2.waitKey()
'''
    while True:
        key = cv2.waitKey()
        if key == 27:
            break;
'''

if __name__ == '__main__':
    main()
#