# -*- coding: utf-8 -*-
"""EWC.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1W3Jdn6cKXLaHUtqUyLf0xdI0e0-1Uhc8
"""
import os

import os
os.environ["CUDA_VISIBLE_DEVICES"]='0'

import torch
from copy import deepcopy

from torch import nn
# from tqdm import tqdm
from torch.nn import functional as F
import torch.optim as optim
import torch.utils.data

from torchvision import datasets, transforms
import random
import PIL.Image as Image

epochs = 10
lr = 1e-3
batch_size = 128
sample_size = 200
hidden_size = 256
num_task = 5
epochs_interval = 1
seed = 42

# device = torch.device("cuda:2")

class SplitMNIST(datasets.MNIST):
    tasks = {
        0: [0,1],
        1: [2,3],
        2: [4,5],
        3: [6,7],
        4: [8,9],
    }
    
    def __init__(self, root="../datasets/mnist", train=True, task=0, cum=True):
        super().__init__(root, train, download=True)
        if not train and cum:
            classes = [i for t in range(task + 1) for i in SplitMNIST.tasks[t]]
        else:
            classes = [i for i in SplitMNIST.tasks[task]]
        self.idx = [i for i in range(len(self.targets)) if self.targets[i] in classes]
        self.transform = transforms.ToTensor()
        self.task = task
        self.train = train
    
    def __len__(self):
        return len(self.idx)

    def __getitem__(self, index):
        img, target = self.data[self.idx[index]], self.targets[self.idx[index]]
        img = Image.fromarray(img.numpy(), mode='L')
        img = self.transform(img)
        
        if self.train:
            target = target #- task*2
        
        return img.view(-1), target

from torchvision import datasets
import torchvision.transforms as transforms
import os


#DCGAN
class discriminator(nn.Module):
    # Network Architecture is exactly same as in infoGAN (https://arxiv.org/abs/1606.03657)
    # Architecture : (64)4c2s-(128)4c2s_BL-FC1024_BL-FC1_S
    def __init__(self):
        super(discriminator, self).__init__()
        self.input_height = 28
        self.input_width = 28
        self.input_dim = 1
        self.output_dim = 10

        self.conv = nn.Sequential(
            nn.Conv2d(self.input_dim, 64, 4, 2, 1),
            nn.LeakyReLU(0.2),
            nn.Conv2d(64, 128, 4, 2, 1),
            nn.BatchNorm2d(128),
            nn.LeakyReLU(0.2),
        )
        self.fc = nn.Sequential(
            nn.Linear(128 * (self.input_height // 4) * (self.input_width // 4), 1024),
            nn.BatchNorm1d(1024),
            nn.LeakyReLU(0.2),
            nn.Linear(1024, self.output_dim),
            # nn.Sigmoid(),
        )
        # initialize_weights(self)
        
    def forward(self, input):
        x = self.conv(input)
        x = x.view(-1, 128 * (self.input_height // 4) * (self.input_width // 4))
        x = self.fc(x)

        return x

class MyLinear(nn.Linear):
    def __init__(self, in_feats, out_feats, bias=True):
        super(MyLinear, self).__init__(in_feats, out_feats, bias=bias)
        # self.masker = Dropout(p=drop_p)

    def forward(self, input, drop_p):
        self.masker = nn.Dropout(p = drop_p)
        masked_weight = self.masker(self.weight)
        return F.linear(input, masked_weight, self.bias)

class MLP_drop(nn.Module):
    def __init__(self, hidden_size=256, tasks=5, task_size=2):
        super(MLP_drop, self).__init__()
        self.fc1 = nn.Linear(28 * 28, hidden_size)
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.fc3 = nn.Linear(hidden_size, hidden_size)
        self.fc4 = nn.Linear(hidden_size, hidden_size)
        self.fc5 = nn.Linear(hidden_size, hidden_size)
        self.bns = nn.ModuleList(
                [nn.BatchNorm1d(hidden_size) for _ in range(5)])
        self.classifier = nn.ModuleList(
           [MyLinear(hidden_size, task_size) for _ in range(tasks)])
        # self.fc6 = nn.Linear(hidden_size, 10)

    def forward(self, input, task):
        x = F.relu(self.bns[0](self.fc1(input)))
        x = F.relu(self.bns[1](self.fc2(x)))
        x = F.relu(self.bns[2](self.fc3(x)))
        x = F.relu(self.bns[3](self.fc4(x)))
        x = F.relu(self.bns[4](self.fc5(x)))
        # x = self.classifier[task](x )
        # x = self.fc6(x)
        tocat = []
        for i in range(5):
          if task == i:
            tocat.append(self.classifier[i](x, drop_p = 0.0))
          else:
            tocat.append(self.classifier[i](x, drop_p = 1.0))

        x = torch.cat([fc for fc in tocat], dim=-1)
        return x

    def predict(self,input,task):
        x = F.relu(self.bns[0](self.fc1(input)))
        x = F.relu(self.bns[1](self.fc2(x)))
        x = F.relu(self.bns[2](self.fc3(x)))
        x = F.relu(self.bns[3](self.fc4(x)))
        x = F.relu(self.bns[4](self.fc5(x)))
        # x = self.classifier[task](x )
        # x = self.fc6(x)
        # tocat = []
        # for i in range(5):
        #   if task == i:
        #     tocat.append(self.classifier[i](x, drop_p = 0.0))
        #   else:
        #     tocat.append(nn.Dropout(p = 0.99)(self.classifier[i](x, drop_p = 0.99)))

        x = torch.cat([fc(x,drop_p = 0.0) for fc in self.classifier], dim=-1)
        return x

EPS = 1e-20
def normalize_fn(fisher):
    return (fisher - fisher.min()) / (fisher.max() - fisher.min() + EPS)

class EWCpp(object):
    def __init__(self, model, model_old, device, alpha=0.9, fisher=None, normalize=True):

        self.model = model
        self.model_old = model_old
        self.model_old_dict = self.model_old.state_dict()

        self.device = device
        self.alpha = alpha
        self.normalize = normalize
        
        if fisher is not None: # initialize as old Fisher Matrix
            self.fisher_old = fisher
            for key in self.fisher_old:
                self.fisher_old[key].requires_grad = False
                self.fisher_old[key] = self.fisher_old[key].to(device)
            self.fisher = deepcopy(fisher)
            if normalize:
                self.fisher_old = {n: normalize_fn(self.fisher_old[n]) for n in self.fisher_old}

        else: # initialize a new Fisher Matrix
            self.fisher_old = None
            self.fisher = {n:torch.zeros_like(p, device=device, requires_grad=False) 
                           for n, p in self.model.named_parameters()} 

    def update(self):
        # suppose model have already grad computed, so we can directly update the fisher by getting model.parameters
        for n, p in self.model.named_parameters():
            if p.grad is not None:
                self.fisher[n] = (self.alpha * p.grad.data.pow(2)) + ((1-self.alpha)*self.fisher[n])

    def get_fisher(self):
        return self.fisher # return the new Fisher matrix

    def penalty(self):
        loss = 0
        loss_last = 0
        if self.fisher_old is None:
            return 0., 0.
        for n, p in self.model.named_parameters():
            if 'classifier' in n:
              loss_last = (self.fisher_old[n] * (p - self.model_old_dict[n]).pow(2)).sum()
            else:
              loss += (self.fisher_old[n] * (p - self.model_old_dict[n]).pow(2)).sum()
        return loss,loss_last

"""# start training procedure"""

def get_mnist():
    train_loader = {}
    test_loader_no_cum = {}
    test_loader = {}

    for i in range(num_task):
        train_loader[i] = torch.utils.data.DataLoader(SplitMNIST(train=True, task=i),
                                                      batch_size=batch_size,)
                                                      # num_workers=4)
        test_loader[i] = torch.utils.data.DataLoader(SplitMNIST(train=False, task=i),
                                                     batch_size=batch_size)
        test_loader_no_cum[i] = torch.utils.data.DataLoader(SplitMNIST(train=False, task=i, cum=False),
                                                     batch_size=batch_size)
    return train_loader, test_loader, test_loader_no_cum

def test(model, data_loader, t):
    model.eval()
    correct = 0.
    size = float(0.)
    for input, target in data_loader:
        input, target = input.cuda(), target.cuda()
        output = model.predict(input, t)
        _, prediction = output.max(1)
        prediction = prediction
        correct += torch.sum(prediction.eq(target)).float()
        size += len(target)
    return correct / size

train_loader, test_loader, test_loader_no_cum = get_mnist()

# for a,b in train_loader[0]:
#   print(a.size())
#   break

"""# Vanilla"""

# def normal_train(model, optimizer, data_loader, task):
#     model.train()
#     epoch_loss = 0
#     for input, target in data_loader:
#         input, target = input.cuda(), target.cuda()
#         optimizer.zero_grad()
#         output = model(input)
#         loss = F.cross_entropy(output, target)
#         epoch_loss += loss
#         loss.backward()
#         optimizer.step()
#     # print(target)
#     return epoch_loss / len(data_loader)

# def standard_process(model, epochs, task):
#     optimizer = optim.Adam(params=model.parameters(), lr=lr)
    
#     for epoch in range(2):
#         loss = normal_train(model, optimizer, train_loader[task], task)
#         if epoch % epochs_interval == 0:
#             print(f"Epoch {epoch + 1}: Loss {loss}")

#     print(f"Acc task {task} is {test(model, test_loader[task], task)}")      
#     return model

# torch.manual_seed(seed)
# torch.cuda.manual_seed(seed)
# model = discriminator().cuda()
# EPS = 1e-20
# 
# for global_epoch in range(25):
#   for task in range(num_task):
#       print("")
#       model = standard_process(model, epochs, task=task)
# 
# # PER TASK ACCURACY
# print("Per task Acc")
# for t in range(num_task):
#     print(f"{t} : {test(model, test_loader_no_cum[t], t).item() :.3f}")
#     
# # TOTAL ACCURACY
# print("Cumulative Acc")
# print(f"{test(model, test_loader[4], t).item() :.3f}")
# 
"""# Online EWC
From: https://arxiv.org/pdf/1805.06370.pdf
"""

# def online_ewc_train(model, optimizer, data_loader, ewc, importance, task):
#     model.train()
#     epoch_loss = 0
#     for input, target in data_loader:
#         input, target = input.cuda(), target.cuda()
#         optimizer.zero_grad()
#         output = model(input, task)
        
#         loss = F.cross_entropy(output, target)
#         loss.backward()
        
#         loss_ewc = importance * ewc.penalty()
#         if loss_ewc != 0.:
#             loss_ewc.backward()
        
#         epoch_loss += loss
        
#         optimizer.step()
#     return epoch_loss / len(data_loader)


# def online_ewc_process(model, ewc, epochs, importance, task):

#     optimizer = optim.Adam(params=model.parameters(), lr=lr)
    
#     for epoch in range(epochs):
#         loss = online_ewc_train(model, optimizer, train_loader[task], ewc, importance, task)
#         if epoch % epochs_interval == 0:
#             print(f"Epoch {epoch + 1}: Loss {loss}")
    
#     ewc.update(train_loader[task], task)
#     # print({k:v.mean().item() for k,v in ewc.get_fisher().items()})
#     # print({k:v.max().item() for k,v in ewc.get_fisher().items()})

#     print(f"Acc task {task} is {test(model, test_loader[task])}")
       
#     return model, ewc

# torch.manual_seed(seed)
# torch.cuda.manual_seed(seed)
# model = MLP().cuda()
# fisher = None
# importance = 75000
# EPS = 1e-20
# phi = 0.95
# 
# for task in range(num_task):
#     model_old = deepcopy(model)
#     for p in model_old.parameters():
#         p.requires_grad = False
# 
#     print("")
#     ewc = OnlineEWC(model, model_old, "cuda", fisher=fisher)
#     model, ewc = online_ewc_process(model, ewc, epochs, task=task, importance=importance)
#     
#     if fisher is None:
#         fisher = deepcopy(ewc.get_fisher())
#        
#         fisher = {n: (fisher[n] - fisher[n].min()) / (fisher[n].max() - fisher[n].min() + EPS) for n in fisher}
#         
#         print("\n New fisher (normalized):")
#         print({n:(p.min().item(), p.median().item(), p.max().item()) for n,p in fisher.items()})
#     else:
#         new_fisher = ewc.get_fisher()
#         for n in fisher:
#             new_fisher[n] = (new_fisher[n] - new_fisher[n].min()) / (new_fisher[n].max() - new_fisher[n].min() + EPS)
#             fisher[n] = phi*fisher[n] + new_fisher[n]
#         print("\n New fisher (normalized):")
#         print({n:(p.min().item(), p.median().item(), p.max().item()) for n,p in fisher.items()})
# 
# # PER TASK ACCURACY
# print("Per task Acc")
# for t in range(num_task):
#     print(f"{t} : {test(model, test_loader_no_cum[t]).item() :.3f}")
#     
# # TOTAL ACCURACY
# print("Cumulative Acc")
# print(f"{test(model, test_loader[4]).item() :.3f}")
# 
"""# EWC ++
From: http://openaccess.thecvf.com/content_ECCV_2018/papers/Arslan_Chaudhry__Riemannian_Walk_ECCV_2018_paper.pdf
"""

def ewcpp_train(model, optimizer, data_loader, ewc, importance, imp_l, task):
    model.train()
    epoch_loss = 0
    for input, target in data_loader:
        input, target = input.cuda(), target.cuda()
        optimizer.zero_grad()
        output = model(input)
        loss = F.cross_entropy(output, target)
        epoch_loss += loss
        loss.backward()
        ewc.update()
        a,b = ewc.penalty()
        loss_ewc = importance * a + imp_l * b
        if loss_ewc != 0:
            loss_ewc.backward()
        optimizer.step()
    return epoch_loss / len(data_loader)

def ewcpp_process(model, ewc, epochs, importance, imp_l, task):

    # optimizer = optim.Adam(params=model.parameters(), lr=lr)
    # optimizer = optim.SGD(params=model.parameters(), lr = lr*0.1, momentum = 0)
    
    my_list = ['classifier.0.weight', 'classifier.0.bias','classifier.1.weight', 'classifier.1.bias','classifier.2.weight', 'classifier.2.bias','classifier.3.weight', 'classifier.3.bias','classifier.4.weight', 'classifier.4.bias',]

    params = list(map(lambda x: x[1],list(filter(lambda kv: kv[0] in my_list, model.named_parameters()))))
    base_params = list(map(lambda x: x[1],list(filter(lambda kv: kv[0] not in my_list, model.named_parameters()))))
    optimizer = optim.SGD(
        [{'params': base_params}, {'params': params, 'lr': lr*0.001}], lr=lr*0.1, momentum=0.0, weight_decay = 0.1
        )
	
    for epoch in range(25):
        loss = ewcpp_train(model, optimizer, train_loader[task], ewc, importance, imp_l, task)
        if epoch % epochs_interval == 0:
            print("Epoch {0}: Loss {1}".format(epoch + 1, loss))

    print("Acc task {0} is {1}".format(task, test(model, test_loader[task], task)))

    return model, ewc

torch.manual_seed(seed)
torch.cuda.manual_seed(seed)

model = MLP().cuda()
fisher = None
importance = 1*(10**(3))*0.0
imp_l = 1*(10**(3))*0.0
EPS = 1e-20
alpha = 0.9
normalize = True
print("neuron freeze, 1e-4, 1e-6 SGD, 25ep, weighdecay 0.1")
for global_epochs in range(1):
  for task in range(num_task):
      model_old = deepcopy(model)
      for p in model_old.parameters():
          p.requires_grad = False

      print("")

      ewc = EWCpp(model, model_old, "cuda", fisher=fisher, alpha=alpha, normalize=normalize)
      model, ewc = ewcpp_process(model, ewc, epochs, task=task, importance=importance, imp_l = imp_l)
    
      fisher = deepcopy(ewc.get_fisher())

  print("\n",global_epochs)
      # print("\n New fisher (not normalized):")
     # print({n:(p.min().item(), p.median().item(), p.max().item()) for n,p in fisher.items()})

# PER TASK ACCURACY
print("Per task Acc")
for t in range(num_task):
    # print()
    print("%.3f"%(test(model, test_loader_no_cum[t], t)))
    
# TOTAL ACCURACY
print("Cumulative Acc")
print("%.3f"%test(model, test_loader[4],4))
