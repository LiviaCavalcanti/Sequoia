import os
import pprint
from collections import OrderedDict, defaultdict
from dataclasses import InitVar, asdict, dataclass
from itertools import accumulate
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, List, Tuple, Type

import matplotlib.pyplot as plt
import simple_parsing
import torch
import torch.utils.data
import tqdm
from simple_parsing import ArgumentParser, choice, field, subparsers
from torch import Tensor, nn, optim
from torch.nn import functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from torchvision.utils import save_image

from common.losses import LossInfo
from common.metrics import Metrics
from config import Config
from datasets.dataset import Dataset
from datasets.mnist import Mnist
from models.classifier import Classifier
from tasks import AuxiliaryTask
from tasks.reconstruction import VAEReconstructionTask
from utils.utils import to_list

from .experiment import Experiment


@dataclass
class IID(Experiment):
    """ Simple IID setting. """
    def __post_init__(self):
        super().__post_init__()
        self.reconstruction_task: Optional[VAEReconstructionTask] = None
        
        # If the model is a SelfSupervised classifier, it will have a `tasks` attribute.
        # find the reconstruction task, if there is one.
        if "reconstruction" in self.model.tasks:
            self.reconstruction_task = self.model.tasks["reconstruction"]
            self.latents_batch = torch.randn(64, self.hparams.hidden_size)
    
    def run(self):
        self.load()
        train_losses, valid_losses = super().train_until_convergence(self.dataset.train, self.dataset.valid, self.hparams.epochs)
        exit()
        train_epoch_losses: List[LossInfo] = []
        valid_epoch_losses: List[LossInfo] = []

        for epoch in range(self.hparams.epochs):
            # Training:
            train_losses: List[LossInfo] = []
            for train_loss in self.train_iter(epoch, self.train_loader):
                train_losses.append(train_loss)
            train_epoch_loss = sum(train_losses, LossInfo())
            train_epoch_losses.append(train_epoch_loss)

            # Validation:
            valid_batch_losses: List[LossInfo] = []
            for valid_loss in self.test_iter(epoch, self.valid_loader):
                valid_batch_losses.append(valid_loss)
            valid_epoch_loss = sum(valid_batch_losses, LossInfo())
            valid_epoch_losses.append(valid_epoch_loss)

            # make the training plots for this epoch
            plots_dict = self.make_plots_for_epoch(epoch, train_losses, valid_batch_losses)
            self.log(plots_dict)
            
            # log the validation loss for this epoch.
            self.log(valid_epoch_loss, prefix="Valid ")

            total_validation_loss = valid_epoch_loss.total_loss.item()
            validation_metrics = valid_epoch_loss.metrics

            print(f"Epoch {epoch}: Total Test Loss: {total_validation_loss}, Validation Metrics: ", repr(valid_epoch_loss.metrics))

        # make the plots using the training and validation losses of each epoch.
        epoch_plots_dict = self.make_plots(train_epoch_losses, valid_epoch_losses)

        # Get the most recent validation metrics. 
        class_accuracy = valid_epoch_losses[-1].metrics.class_accuracy
        valid_class_accuracy_mean = class_accuracy.mean()
        valid_class_accuracy_std = class_accuracy.std()
        self.log("Validation Average Class Accuracy: ", valid_class_accuracy_mean, once=True, always_print=True)
        self.log("Validation Class Accuracy STD:", valid_class_accuracy_std, once=True, always_print=True)
        self.log(epoch_plots_dict, once=True)

        return epoch_plots_dict

    def make_plots_for_epoch(self,
                             epoch: int,
                             train_losses: List[LossInfo],
                             valid_losses: List[LossInfo]) -> Dict[str, plt.Figure]:
        train_x: List[int] = list(accumulate([
            loss.metrics.n_samples for loss in train_losses
        ]))
        
        fig: plt.Figure = plt.figure()
        ax1: plt.Axes = fig.add_subplot(1, 2, 1)
        ax1.set_title(f"Loss - Epoch {epoch}")
        ax1.set_xlabel("# of Samples")
        ax1.set_ylabel("Training Loss")
        
        # Plot the evolution of the training loss
        total_train_losses: List[float] = to_list(loss.total_loss for loss in train_losses)
        ax1.plot(train_x, total_train_losses, label="total loss")

        from utils.utils import to_dict_of_lists
        train_losses_dict = to_dict_of_lists([loss.losses for loss in train_losses])

        # Plot all the other losses (auxiliary losses)
        for loss_name, aux_losses in train_losses_dict.items():
            ax1.plot(train_x, aux_losses, label=loss_name)
        ax1.legend(loc='upper right')
        
        # add the vertical lines for task transitions (if any)
        for task_info in self.dataset.train_tasks:
            ax1.axvline(x=min(task_info.indices), color='r')

        
        n_classes = self.dataset.y_shape[0]
        classes = list(range(n_classes))
        class_accuracy = sum(valid_losses, LossInfo()).metrics.class_accuracy
        ax2: plt.Axes = fig.add_subplot(1, 2, 2)
        
        ax2.bar(classes, class_accuracy)
        ax2.set_xlabel("Class")
        ax2.set_xticks(classes)
        ax2.set_xticklabels(classes)
        ax2.set_ylabel("Validation Accuracy")
        ax2.set_ylim(0.0, 1.0)
        ax2.set_title(f"Validation Class Accuracy After Epoch {epoch}")
        # fig.tight_layout()
        
        if self.config.debug and self.config.verbose:
            fig.show()
            fig.waitforbuttonpress(timeout=30)
        fig.savefig(self.plots_dir / f"epoch_{epoch}.jpg")
        
        return {"epoch_loss": fig}

    def make_plots(self, train_losses: List[LossInfo], valid_losses: List[LossInfo]) -> Dict[str, plt.Figure]:
        n_epochs = len(train_losses)
        epochs = list(range(n_epochs))
        plots_dict: Dict[str, plt.Figure] = {}

        fig: plt.Figure = plt.figure()
        ax: plt.Axes = fig.subplots()
        
        ax.set_title("Total Loss")
        ax.set_xlabel("Epoch")
        ax.set_xticks(epochs)
        ax.set_ylabel("Loss")
        ax.plot(epochs, [loss.total_loss for loss in train_losses], label="train")
        ax.plot(epochs, [loss.total_loss for loss in valid_losses], label="valid")
        ax.legend(loc='upper right')

        if self.config.debug:
            fig.show()
            fig.waitforbuttonpress(timeout=30)
        plots_dict["losses"] = fig
        fig.savefig(self.plots_dir / "losses.jpg")

        fig, ax = plt.subplots()
        ax.set_xlabel("Epoch")
        ax.set_ylim(0.0, 1.0)
        ax.set_ylabel("Accuracy")
        ax.set_title("Training and Validation Accuracy")
        ax.plot(epochs, [loss.metrics.accuracy for loss in train_losses], label="train")
        ax.plot(epochs, [loss.metrics.accuracy for loss in valid_losses], label="valid")
        ax.legend(loc='lower right')
        

        if self.config.debug:
            fig.show()
            fig.waitforbuttonpress(timeout=30)

        plots_dict["accuracy"] = fig
        fig.savefig(self.plots_dir / "accuracy.jpg")
        return plots_dict


    def test_iter(self, dataloader: DataLoader):
        yield from super().test_iter(dataloader)
        if self.reconstruction_task:
            self.generate_samples()
    
    def train_iter(self, dataloader: DataLoader):
        for loss_info in super().train_iter(dataloader):
            yield loss_info
        
        if self.reconstruction_task:
            # use the last batch of x's.
            x_batch = loss_info.tensors.get("x")
            if x_batch is not None:
                self.reconstruct_samples(x_batch)
        
        
    def reconstruct_samples(self, data: Tensor):
        with torch.no_grad():
            n = min(data.size(0), 8)
            
            originals = data[:n]
            reconstructed = self.reconstruction_task.reconstruct(originals)
            comparison = torch.cat([originals, reconstructed])

            reconstruction_images_dir = self.config.log_dir / "reconstruction"
            reconstruction_images_dir.mkdir(exist_ok=True)
            file_name = reconstruction_images_dir / f"reconstruction_step_{self.global_step}.png"
            
            save_image(comparison.cpu(), file_name, nrow=n)

    def generate_samples(self):
        with torch.no_grad():
            n = 64
            fake_samples = self.reconstruction_task.generate(torch.randn(64, self.hparams.hidden_size))
            fake_samples = fake_samples.cpu().view(n, *self.dataset.x_shape)

            generation_images_dir = self.config.log_dir / "generated_samples"
            generation_images_dir.mkdir(exist_ok=True)
            file_name = generation_images_dir / f"generated_step_{self.global_step}.png"
            save_image(fake_samples, file_name)

