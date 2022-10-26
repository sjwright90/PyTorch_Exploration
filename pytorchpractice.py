

#%%

from itertools import accumulate
import random
from ssl import enum_certificates
import torch
import torch.nn as nn
import torchvision
import torch.utils.data
from torch.utils.data import DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
import torchvision.transforms as transforms
import torch.optim as optim
import torch.nn.functional as F
import time
import numpy as np
import matplotlib.pyplot as plt

#%%
#set the device to "gpu" this script was written on a 
#'macOS-12.6-arm64-arm-64bit' platform with
#torch version '1.12.1'. The code to move to gpu might be different
#depending on your machine, or may not be available.
#python version 3.10.6
mps_on = torch.has_mps

if mps_on:
    devicemps = torch.device("mps")
#I believe this is "cuda" for nvidia machines
#%%
#define accuracy function

def accuracy(outputs, labels):
    _, pred = torch.max(outputs, dim=1)
    return torch.tensor(torch.sum(pred == labels).item()/len(pred))

#%%
#define how to transform the images for processing
transform = transforms.Compose([transforms.ToTensor(),\
    transforms.Normalize((0.5,0.5,0.5), (0.5,0.5,0.5))])
#just use a really simple assumption that the mean and std dev
#of each channel is 0.5

#then we pull the training and test sets in
#using the cifar10 dataset, we will store in in a local
#folder called 'data'
cifartrain = torchvision.datasets.CIFAR10(root = "./data",\
    train = True, download = True, transform = transform)
cifartest = torchvision.datasets.CIFAR10(root = "./data",\
    train = False, download=True, transform = transform)

#and make a list of the images in the dataset
classes = cifartrain.classes
#%%
#then we build the data loaders to get the data 
#into the pytorch model
#we will manually build a k-fold CV from the training set
#so no just put 
indxs = np.arange(len(cifartrain))
np.random.shuffle(indxs)
split = int(np.floor(len(cifartrain) * 0.1)) #10% set aside for validation
train_idx, val_idx = indxs[split:], indxs[:split]
train_sampler = SubsetRandomSampler(train_idx)
valid_sampler = SubsetRandomSampler(val_idx)
#%%
trainload = DataLoader(cifartrain, batch_size = 128,\
    sampler=train_sampler, num_workers=0, pin_memory=True)

valload = DataLoader(cifartrain, batch_size = 128,\
    sampler=valid_sampler, num_workers=0, pin_memory=True)

testloader = DataLoader(cifartest, batch_size = 128,\
    num_workers=0, pin_memory=True)


#load in 128 at a time
#workers set to 0 because it freezes otherwise and I cannot figure out why
#seems to be a unique problem to mps GPU usage

#%%


#%%
#plot some of the images
def showimg(img):
    img = img/2 + 0.5
    plt.imshow(np.transpose(img, (1,2,0)))
def get_show_image(d_loader = trainload, n_show = 20):
    set_row = n_show//10 if n_show%10 == 0 else n_show//10 + 1
    diter = iter(d_loader)
    images, label = diter.next()
    images = images.numpy()
    fig = plt.figure(figsize=(25,4))
    for idx in np.arange(n_show):
        ax = fig.add_subplot(set_row, 10, idx + 1, xticks = [], yticks = [])
        showimg(images[idx])
        ax.set_title(classes[label[idx]])


#%%
#we will then start to put together a model
#going for simple here, so building a feed forward model utilizing
#the sequetial module offered in pytorch

class CIFARNet(nn.Module):
    def __init__(self, n_classes = 10): #make it somewhat reusable by allowing user to define n_classes
        super(CIFARNet, self).__init__()
        self.convo = nn.Sequential(
            nn.Conv2d(in_channels=3, out_channels=16, kernel_size=3, padding=1),
            nn.ReLU(inplace = True),
            nn.Conv2d(in_channels=16, out_channels = 32, kernel_size=3, padding=1),
            nn.ReLU(inplace = True),
            nn.MaxPool2d(kernel_size=2, stride = 2), #size 32 x 16 x 16
            nn.Conv2d(in_channels=32, out_channels = 64, kernel_size=3, padding=1),
            nn.ReLU(inplace = True),
            nn.BatchNorm2d(64),
            nn.Conv2d(in_channels=64, out_channels = 128, kernel_size=3, padding=1),
            nn.ReLU(inplace = True),
            nn.MaxPool2d(kernel_size = 2, stride = 2), #size 128 x 8 x 8
            nn.BatchNorm2d(128)
        )
        self.avgpool = nn.AdaptiveAvgPool2d((6,6)) # out: 128 x 6 x 6
        self.linear = nn.Sequential(
            nn.Dropout(),
            nn.Linear(128*6*6, 1024),
            nn.ReLU(inplace = True),
            nn.Dropout(),
            nn.Linear(1024, 1024),
            nn.ReLU(inplace = True),
            nn.Linear(1024,n_classes)            
        )
    def forward(self, x):
        x = self.convo(x)
        x = self.avgpool(x)
        x = x.view(-1, 128 * 6 * 6)
        x = self.linear(x)
        return x
#%%
#set up hyperparameters and optimizer
model = CIFARNet()
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr = 3e-3, weight_decay=0.0001)
if mps_on: model.to(devicemps)
#%%
"""make sure the model is outputting the expected results"""
for images, labels in trainload:
    if mps_on: 
            images = images.to(devicemps)
            labels = labels.to(devicemps)
    print("images.shape", images.shape)
    out = model(images)
    print("out.shape", out.shape)
    print("out[0]", out[0])
    break
#%%
start_time = time.time()
batch_loss, train_accuracy, pred_accuracy = [],[],[]
best_val_acc, best_epoch = -np.inf, 0
for epoch in range(10):
    epoch_start_time = time.time()
    model.train()
    for batch_idx, (feats, targets) in enumerate(trainload):
        if mps_on: 
            feats = feats.to(devicemps)
            targets = targets.to(devicemps)
        optimizer.zero_grad()
        output = model(feats)
        loss = criterion(output, targets)
        batch_loss.append(loss)
        train_accuracy.append(accuracy(output, targets))
        loss.backward()
        optimizer.step()
    print("Batch time: {:.3f} minutes".format((time.time()-epoch_start_time)/60))

    val_start_time = time.time()
    model.eval()
    for val_idx, (feats, targets)  in enumerate(valload):
        if mps_on:
            feats, targets = feats.to(devicemps), targets.to(devicemps)
        output = model(feats)
        loss = criterion(output, targets)
        temp = accuracy(output, targets)
        pred_accuracy.append(temp)
        if temp > best_val_acc:
            best_val_acc = temp
            best_epoch = epoch
    print("Validation runtime: {:.3f} minutes".format((time.time()-val_start_time)/60))

print("Total time: {:.3f} minutes".format((time.time()-start_time)/60))
#%%