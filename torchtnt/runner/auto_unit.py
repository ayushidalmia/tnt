# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# ignore errors due to `Any` type
# pyre-ignore-all-errors[2]
# pyre-ignore-all-errors[3]

from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple

import torch
from torchtnt.runner.state import State
from torchtnt.runner.unit import TrainUnit, TTrainData
from torchtnt.utils import copy_data_to_device, get_device_from_env
from typing_extensions import Literal


class AutoTrainUnit(TrainUnit[TTrainData], ABC):
    """
    The AutoTrainUnit is a convenience for users who are training with stochastic gradient descent and would like to have model optimization
    handled for them. The AutoTrainUnit subclasses TrainUnit, and runs the train_step for the user, specifically: forward pass, loss computation,
    backward pass, and optimizer step. To benefit from the AutoTrainUnit, the user must subclass it and implement the `compute_loss` method, and
    optionally the `update_metrics` and `log_metrics` methods. Then use with the `train` or `fit` entry point as normal.

    For more advanced customization, the basic TrainUnit interface may be a better fit.

    Args:
        optimizer: optimizer to be used during training.
        lr_scheduler: lr_scheduler to be used during training.
        step_lr_interval: whether to step lr_scheduler every step or every epoch. Defaults to every epoch.
        device: the device to be used.
        log_frequency_steps: how often to log in terms of steps (parameter updates)

    Attributes:
        optimizer: optimizer to be used during training.
        lr_scheduler: lr_scheduler to be used during training.
        step_lr_interval: whether to step lr_scheduler every step or every epoch. Defaults to every epoch.
        device: the device to be used.
        log_frequency_steps: how often to log in terms of steps (parameter updates)
    """

    def __init__(
        self,
        *,
        optimizer: torch.optim.Optimizer,
        lr_scheduler: Optional[torch.optim.lr_scheduler._LRScheduler] = None,
        step_lr_interval: Literal["step", "epoch"] = "epoch",
        device: Optional[torch.device] = None,
        log_frequency_steps: int,
    ) -> None:
        super().__init__()
        self.optimizer = optimizer
        self.lr_scheduler = lr_scheduler
        self.step_lr_interval = step_lr_interval
        self.device: torch.device = device or get_device_from_env()
        self.log_frequency_steps: int = log_frequency_steps

        # TODO: Make AutoTrainUnit work when data type is Iterator

    @abstractmethod
    def compute_loss(self, state: State, data: TTrainData) -> Tuple[torch.Tensor, Any]:
        """
        The user should implement this method with their loss computation. This will be called every `train_step`.

        Args:
            state: a State object which is passed from the `train_step`
            data: a batch of data which is passed from the `train_step`

        Returns:
            Tuple containing the loss and the output of the model
        """
        ...

    def update_metrics(
        self, state: State, data: TTrainData, loss: torch.Tensor, outputs: Any
    ) -> None:
        """
        The user should implement this method with code to update metrics. This will be called every `train_step`.

        Args:
            state: a State object which is passed from the `train_step`
            data: a batch of data which is passed from the `train_step`
            outputs: the outputs of the model forward pass
        """
        pass

    def log_metrics(
        self, state: State, step: int, interval: Literal["step", "epoch"]
    ) -> None:
        """
        The user should implement this method with their code to log metrics. This will be called based on `log_frequency_steps`
        and how many parameter updates have been run on the model.

        Args:
            state: a State object which is passed from the `train_step`
            step: how many steps have been completed (i.e. how many parameter updates have been run on the model)
            interval: whether `log_metrics` is called at the end of a step or at the end of an epoch
        """
        pass

    def train_step(self, state: State, data: TTrainData) -> Tuple[torch.Tensor, Any]:
        data = copy_data_to_device(data, self.device)
        # users must override this
        loss, outputs = self.compute_loss(state, data)
        loss.backward()

        # optimizer step
        self.optimizer.step()
        # sets gradients to zero
        self.optimizer.zero_grad(set_to_none=True)

        if self.lr_scheduler and self.step_lr_interval == "step":
            self.lr_scheduler.step()

        # users can override this, by default this is a no-op
        self.update_metrics(state, data, loss, outputs)

        assert state.train_state
        step_count = state.train_state.progress.num_steps_completed
        if (step_count + 1) % self.log_frequency_steps == 0:
            # users can override this, by default this is a no-op
            self.log_metrics(state, step_count, "step")

        return loss, outputs

    def on_train_epoch_end(self, state: State) -> None:
        # step the learning rate scheduler
        # note: if user wants to override on_train_epoch_end themselves, they should remember to call up to this method via super().on_train_epoch_end()
        if self.lr_scheduler and self.step_lr_interval == "epoch":
            self.lr_scheduler.step()

        assert state.train_state
        step_count = state.train_state.progress.num_steps_completed
        # users can override this, by default this is a no-op
        self.log_metrics(state, step_count, "epoch")
