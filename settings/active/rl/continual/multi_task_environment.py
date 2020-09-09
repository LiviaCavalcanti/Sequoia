from collections import OrderedDict
from typing import Dict, List, Optional, Sequence

import gym
import matplotlib.pyplot as plt
import numpy as np
from gym.envs.classic_control import CartPoleEnv

from utils.logging_utils import get_logger

task_param_names: Dict[str, List[str]] = {
    CartPoleEnv: [
        "gravity",
        "masscart",
        "masspole",
        "length",
        "force_mag",
        "tau",
    ]
}

logger = get_logger(__file__)

class MultiTaskEnvironment(gym.Wrapper):
    """ Wrapper for an environment that adds the ability to randomly switch the
    'task' by modifying properties of the environment, physics, or of the agent.

    """
    def __init__(self,
                 env: gym.Env,
                 task_params: List[str] = None,
                 task_schedule: Dict[int, Dict[str, float]] = None,
                 noise_std: float = 0.2):
        """Wraps an environment to allow it to be 'multi-task'.

        NOTE: Assumes that all the attributes in 'task_param_names' are floats
        for now.

        Args:
            env (gym.Env): The environment to wrap.
            task_param_names (List[str], optional): The attributes of the
                environment that will be allowed to change. Defaults to None.
            task_schedule (Dict[int, Dict[str, float]], optional): Schedule
                mapping from a given step number to the state that will be set
                at that time.
            noise_std (float, optional): The standard deviation of the noise
                used to create the different tasks.
        """
        super().__init__(env=env)
        self.env = env
        self.noise_std = noise_std
        if not task_params:
            # TODO: Remove this.
            unwrapped_type = type(env.unwrapped)
            if unwrapped_type in task_param_names:
                task_params = task_param_names[unwrapped_type]
            else:
                logger.warning(UserWarning(
                    f"You didn't pass any 'task params', and the task "
                    f"parameters aren't known for this env ({env}), so we can't "
                    f"make it multi-task with this wrapper."
                ))
        self.task_schedule = task_schedule or {}
        self.task_params: List[str] = task_params
        self.default_task = self.get_current_task().copy()
        self.default_task_dict: Dict[str, float] = self.current_task_dict()
        self._step: int = 0

    def step(self, *args, **kwargs):
        # If we reach a step in the task schedule, then we change the task to
        # that given step.
        if self._step in self.task_schedule:
            self.update_task(self.task_schedule[self._step])
        super().step(*args, **kwargs)
        self._step += 1

    # @property
    # def current_task(self) -> Optional[np.ndarray]:
    def get_current_task(self) -> Optional[np.ndarray]:
        if not self.task_params:
            # No defined parameters to change, so returning None.
            return None
        return np.array([
            # NOTE: We get the attributes from the unwrapped environment, which
            # effectively bypasses any wrappers. Don't know if this is good
            # practice, but oh well.
            getattr(self.env.unwrapped, name) for name in self.task_params
        ])

    # @current_task.setter
    def set_current_task(self, value: Sequence[float]):
        assert len(value) == len(self.task_params), "lengths should match!"
        for name, param_value in zip(self.task_params, value):
            assert hasattr(self.env.unwrapped, name), (
                f"the unwrapped environment doesn't have a {name} attribute!"
            )
            setattr(self.env.unwrapped, name, param_value)

    def current_task_dict(self) -> Dict[str, float]:
        return OrderedDict(zip(self.task_params, self.current_task))

    #FIXME: Seems like we can't use a @property decorator on a Wrapper? 
    current_task = property(get_current_task, set_current_task)
    
    def random_task(self) -> np.ndarray:
        mult = np.random.normal(
            loc=1,
            scale=self.noise_std,
            size=self.default_task.shape,
        )
        # Only allow values from 0.1 to 3 times the default task parameters.
        mult = mult.clip(0.1, 3.0)
        task = mult * self.default_task
        return task

    def update_task(self, values: Sequence[float] = None, **kwargs):
        """Updates the current ask with the values.
        """
        if values:
            new_task = values
        elif kwargs:    
            d = self.current_task_dict()
            d.update(kwargs)
            new_task = [d[k] for k in self.task_params]
        else:
            new_task = self.random_task()
        self.current_task = np.asarray(new_task)
        self.set_current_task(self.current_task)

    def reset(self, new_task: bool = False, **kwargs):
        if new_task:
            self.current_task = self.random_task()
            # idk why this is needed, but whatever.
            self.set_current_task(self.current_task)
        super().reset(**kwargs)

    def seed(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            np.random.seed(seed)
        super().seed(seed)

def MultiTaskCartPole():
    env = gym.make("CartPole-v0")
    return MultiTaskEnvironment(env, noise_std=0.5)