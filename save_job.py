import torch
import torch.multiprocessing as mp
from pathlib import Path
from experiment import Experiment
import logging
logger = mp.get_logger()
logger.setLevel(logging.DEBUG)
from typing import *
from torch import Tensor
from config import Config
import wandb
from models.classifier import Classifier
from utils.json_utils import JsonSerializable


class SaverWorker(mp.Process):
    def __init__(self, config: Config, q: mp.Queue):
        super().__init__()
        self.config = config
        self.q = q

    def run(self):
        print(f"Starting a background thread. (inside Worker)")
        logger.info(f"Config: {self.config}")
        # if config.use_wandb:
        #     wandb.init(project="falr", config=hp.as_dict, group=hp.md5, job_type='background')
        item = self.q.get()
        while item is not None:
            if isinstance(item, dict) and "save_dir" in item:
                self.save(**item)
            item = self.q.get()

    def save(self, save_dir: Path, state: Experiment.State, model_state_dict: Dict[str, Tensor]=None) -> None:
        # TODO: Make this work for any kind of JsonSerializable object, not just State.
        # (Use functools.singledispatch to choose what kind of saving to do.)
        logger.debug(
            f"Asked to save {type(state)} object to path {save_dir}." +
            (f" and the model weights to path {state.model_weights_path}."
                if model_state_dict else ".")
        )
        save_dir.mkdir(parents=True, exist_ok=True)

        saved_weights_path = save_dir / "model_weights.pth"
        if model_state_dict:
            torch.save(model_state_dict, saved_weights_path)    
            state.model_weights_path = saved_weights_path

        save_json_path = save_dir / "state.json"
        save_json_tmp_path = save_json_path.with_suffix(".tmp")
        # Save to the .tmp file (such that if the saving crashes or is interrupted,
        # we don't leave the file in a corrupted state.)
        state.save_json(save_json_tmp_path)
        save_json_tmp_path.replace(save_json_path)
        message = {
            "global step": state.global_step,
        }
        if hasattr(state, "i"):
            message["i"] = state.i
        if hasattr(state, "j"):
            message["j"] = state.j
        logging.debug(f"Finished saving state {message} to directory {save_dir}")