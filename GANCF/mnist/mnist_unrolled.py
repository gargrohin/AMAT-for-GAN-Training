import comet_ml
comet_ml.config.save(api_key="CX4nLhknze90b8yiN2WMZs9Vw")

# prerequisites
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
from torch.autograd import Variable
from torchvision.utils import save_image
import numpy as np
import os
from torch.utils.data import Dataset, DataLoader
import torchvision.utils as vutils
import copy
from PIL import Image

# Device configuration
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print("device: ", device)

bs = 100

# MNIST Dataset
transform = transforms.Compose([
    transforms.Scale(64),
    transforms.ToTensor(),
    transforms.Normalize(mean=(0.5), std=(0.5))])

dataset = datasets.MNIST(root='../datasets/mnist_data/', transform=transform, download=True)

# Data Loader (Input Pipeline)
# dataloader = torch.utils.data.DataLoader(dataset=dataset, batch_size=bs, shuffle=True, num_workers=2)

dataset_ordered = []
for i in range(10):
  dataset_ordered.append(dataset.data[dataset.targets==i])

data_split1 = None
for i in range(5):
    if i == 0:
        data_split1 = dataset_ordered[i]
    else:
        data_split1 = np.concatenate((data_split1, dataset_ordered[i]))

data_split2 = None
for i in range(5,10):
    if i == 5:
        data_split2 = dataset_ordered[i]
    else:
        data_split2 = np.concatenate((data_split2, dataset_ordered[i]))

# data_split1 = data_split1.reshape((data_split1.shape[0], 1, 28,28))
# data_split2 = data_split2.reshape((data_split2.shape[0], 1, 28,28))

class mnistSplit(Dataset):
    def __init__(self, data, transform = None):
        self.data = data
        self.transform = transform
    
    def __len__(self):
        return self.data.shape[0]
    
    def __getitem__(self,idx):
        sample = self.data[idx]
        sample = Image.fromarray(sample, mode='L')
        sample = self.transform(sample)
        # sample = sample.view(-1,1,64,64)

        return sample
# dataloaders_ordered = []
# for dataset in dataset_ordered:
#   dataloaders_ordered.append(DataLoader(dataset, batch_size = args.batch_size, shuffle = True))
dataset1 = mnistSplit(data_split1, transform)
dataset2 = mnistSplit(data_split2, transform)

dataloader = torch.utils.data.DataLoader(dataset=dataset1, batch_size=bs, shuffle=True, num_workers=2)
dataloader2 = torch.utils.data.DataLoader(dataset=dataset2, batch_size=bs, shuffle=True, num_workers=2)

# DCGAN
class generator(nn.Module):
    def __init__(self):
        super(generator, self).__init__()
        self.main = nn.Sequential(
            # input is Z, going into a convolution
            nn.ConvTranspose2d(z_dim, ngf * 8, 4, 1, 0, bias=False),
            nn.BatchNorm2d(ngf * 8),
            nn.ReLU(True),
            # state size. (ngf*8) x 4 x 4
            nn.ConvTranspose2d(ngf * 8, ngf * 4, 4, 2, 1, bias=False),
            nn.BatchNorm2d(ngf * 4),
            nn.ReLU(True),
            # state size. (ngf*4) x 8 x 8
            nn.ConvTranspose2d(ngf * 4, ngf * 2, 4, 2, 1, bias=False),
            nn.BatchNorm2d(ngf * 2),
            nn.ReLU(True),
            # state size. (ngf*2) x 16 x 16
            nn.ConvTranspose2d(ngf * 2, ngf, 4, 2, 1, bias=False),
            nn.BatchNorm2d(ngf),
            nn.ReLU(True),
            # state size. (ngf) x 32 x 32
            nn.ConvTranspose2d(ngf, nc, 4, 2, 1, bias=False),
            nn.Tanh()
            # state size. (nc) x 64 x 64
        )

    def forward(self, input):
        # if input.is_cuda and self.ngpu > 1:
        #     output = nn.parallel.data_parallel(self.main, input, range(self.ngpu))
        # else:
        output = self.main(input)
        return output

class LayerNorm2d(nn.Module):
    """Layer for 2D layer normalization in CNNs.

    PyTorch's LayerNorm layer only works on the last channel, but PyTorch uses
    NCHW ordering in images. This layer moves the channel axis to the end,
    applies layer-norm, then permutes back.
    """

    def __init__(self, out_channels):
        """Initialize the child layer norm layer."""
        super().__init__()
        self.norm = nn.LayerNorm(out_channels)

    def forward(self, inputs):
        """Apply layer normalization."""
        inputs = inputs.permute(0, 2, 3, 1)
        normed = self.norm(inputs)
        outputs = normed.permute(0, 3, 1, 2)
        return outputs

#DCGAN
class discriminator(nn.Module):
    def __init__(self):
        super(discriminator, self).__init__()
        self.main = nn.Sequential(
            # input is (nc) x 64 x 64
            nn.Conv2d(nc, ndf, 4, 2, 1, bias=False),
            nn.LeakyReLU(0.2, inplace=True),
            # state size. (ndf) x 32 x 32
            nn.Conv2d(ndf, ndf * 2, 4, 2, 1, bias=False),
            nn.BatchNorm2d(ndf * 2),
            nn.LeakyReLU(0.2, inplace=True),
            # state size. (ndf*2) x 16 x 16
            nn.Conv2d(ndf * 2, ndf * 4, 4, 2, 1, bias=False),
            nn.BatchNorm2d(ndf * 4),
            nn.LeakyReLU(0.2, inplace=True),
            # state size. (ndf*4) x 8 x 8
            nn.Conv2d(ndf * 4, ndf * 8, 4, 2, 1, bias=False),
            nn.BatchNorm2d(ndf * 8),
            nn.LeakyReLU(0.2, inplace=True),
            # state size. (ndf*8) x 4 x 4
            nn.Conv2d(ndf * 8, 1, 4, 1, 0, bias=False),
            nn.Sigmoid()
        )

    def forward(self, input):
        # if input.is_cuda and self.ngpu > 1:
        #     output = nn.parallel.data_parallel(self.main, input, range(self.ngpu))
        # else:
        output = self.main(input)

        return output.view(-1, 1).squeeze(1)


# build network
z_dim = 100
nc = 1
ngf = 64
ndf = 64
# mnist_dim = train_dataset.data.size(1) * train_dataset.data.size(2)
unrolled_steps = 1
G = generator().to(device)
D = discriminator().to(device)

# loss
criterion = nn.BCELoss() 

# optimizer
lr = 0.0001
G_optimizer = optim.Adam(G.parameters(), lr = lr*2, betas = (0.5, 0.999))
D_optimizer = optim.Adam(D.parameters(), lr = lr/5, betas = (0.5, 0.999))

def D_train(x, z = None, flag = False):
    #=======================Train the discriminator=======================#
    D.zero_grad()

    # train discriminator on real
    x_real, y_real = x, torch.ones(x.size()[0], 1)
    x_real, y_real = Variable(x_real.to(device)), Variable(y_real.to(device))

    D_output_real = D(x_real)
    D_real_loss = criterion(D_output_real, y_real)
    D_real_score = D_output_real

    # train discriminator on facke
    if z == None:
        z = Variable(torch.randn(bs, z_dim, 1, 1).to(device))
    x_fake, y_fake = G(z), Variable(torch.zeros(bs, 1).to(device))

    D_output_fake = D(x_fake)
    D_fake_loss = criterion(D_output_fake, y_fake)
    D_fake_score = D_output_fake

    D_acc = get_critic_acc(D_output_fake, D_output_real)

    # gradient backprop & optimize ONLY D's parameters
    D_loss = D_real_loss + D_fake_loss
    if flag:
        D_loss.backward(create_graph=True)
    else:
        D_loss.backward()
        flag = False
    D_optimizer.step()
        
    return  D_loss.data.item(), D_acc

def G_train(x):
    #=======================Train the generator=======================#
    G.zero_grad()

    z = Variable(torch.randn(bs, z_dim, 1, 1).to(device))
    y = Variable(torch.ones(bs, 1).to(device))

    if unrolled_steps > 0:
        backup = copy.deepcopy(D)
        for i in range(unrolled_steps):
            D_train(x, z = z, flag=True)

    G_output = G(z)
    D_output = D(G_output)
    G_loss = criterion(D_output, y)

    # gradient backprop & optimize ONLY G's parameters
    G_loss.backward()
    G_optimizer.step()


        
    return G_loss.data.item()

def get_critic_acc(critic_fake, critic_real):
    acc = 0.0
    for x in critic_fake[:]:
        if x.item() <= 0.5:
            acc = acc + 1
    for x in critic_real[:]:
        if x.item() >= 0.5:
            acc = acc + 1
    
    acc = acc/(critic_fake.size()[0] + critic_real.size()[0])
    return acc

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

experiment = comet_ml.Experiment(project_name="mnistsplit_unrolled_dcgan")

exp_parameters = {
    "data": "mnist_64x64",
    "model": "64xDConv",
    "opt_gen": "Adam_lr_0.0002, (0,5,0.999)",
    "opt_dis": "Adam_lr_0.0002, (0.5,0.999)",
    "z_dim": 100,
    "unrolled steps": 1,
    "n_critic": 1,
    "normalize": "mean:0.5, std:0.5",
    "dis_landscape": 0,
    "try": 0
}

experiment.log_parameters(exp_parameters)

experiment.train()

output = '.temp_0.png'
n_epoch = 200
n_critic = 1
for epoch in range(1, n_epoch+1):
    G.train()
    D_losses, D_accuracy, G_losses = [], [], []
    if epoch >10:
        dl = dataloader
    else:
        dl = dataloader2
    for batch_idx, x in enumerate(dl):
        D_loss, D_acc = D_train(x)
        D_losses.append(D_loss)
        D_accuracy.append(D_acc)
        if batch_idx % n_critic == 0:
            G_losses.append(G_train(x))
        
    print('[%d/%d]: loss_d: %.3f, acc_d: %.3f, loss_g: %.3f' % (
            (epoch), n_epoch, torch.mean(torch.FloatTensor(D_losses)), torch.mean(torch.FloatTensor(D_accuracy)), torch.mean(torch.FloatTensor(G_losses))))

    # path_to_save = "../models/mnist_dcgan_2/dc64_ganns_"
    # if epoch%10 == 0:
    #     torch.save(D.state_dict(), path_to_save + str(epoch) + "_D.pth")
    #     torch.save(G.state_dict(), path_to_save + str(epoch) + "_G.pth")
    #     print("................checkpoint created...............")
    
    with torch.no_grad():
        G.eval()
        test_z = Variable(torch.randn(64, z_dim, 1, 1).to(device))
        generated = G(test_z).detach().cpu()

        experiment.log_metric("critic_loss", torch.mean(torch.FloatTensor(D_losses)))
        experiment.log_metric("gen_loss", torch.mean(torch.FloatTensor(G_losses)))
        experiment.log_metric("critic_acc", torch.mean(torch.FloatTensor(D_accuracy)))

        vutils.save_image(generated, output ,normalize=True)

        # for x in dl:
        #     break
        # x = x[:64]

        experiment.log_image(output, name = "output_" + str(epoch))
        # x = x.detach().cpu()

        # vutils.save_image(x, output ,normalize=True)

        # experiment.log_image(output, name = "real_" + str(epoch))
        
# # Sample data to get discriminator landscape.
# samples = []
# done = []
# for i in range(10):
#     done.append(0)
# for x,y in train_loader:
#     if done[y[0]] == 0:
#         samples.append(x[0])
#         done[y[0]]=1

# print()
# print(samples[0].size())

# D_outs = []
# # for dataloader in dataloaders_ordered:
# for img in samples:
#     D_outs.append(torch.mean(D(img.view(-1, mnist_dim).float().cuda())).cpu().detach().numpy())

# plt.ylim((0,1))
# for i in range(10):
#     plt.scatter(i,D_outs[i], c = 'g')
#     print(i , D_outs[i])
# experiment.log_figure(figure=plt, figure_name = "dis_modes")
# plt.close()
