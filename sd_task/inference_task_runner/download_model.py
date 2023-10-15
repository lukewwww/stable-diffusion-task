import validators
import hashlib
import os
import urllib3
from sd_task.config import ProxyConfig
from tqdm import tqdm
from sd_task.inference_task_args.task_args import InferenceTaskArgs
from diffusers import ModelMixin
from diffusers.loaders import LoraLoaderMixin, load_textual_inversion_state_dicts
from typing import Callable
import torch


def check_and_prepare_models(
        task_args: InferenceTaskArgs,
        **kwargs):

    task_args.base_model = check_and_download_model_by_name(
        task_args.base_model,
        ModelMixin.from_pretrained,
        **kwargs
    )

    if task_args.vae is not None:
        task_args.vae = check_and_download_model_by_name(
            task_args.vae,
            ModelMixin.from_pretrained,
            **kwargs
        )

    if task_args.controlnet is not None:
        task_args.controlnet.model = check_and_download_model_by_name(
            task_args.controlnet.model,
            ModelMixin.from_pretrained,
            **kwargs
        )

    if task_args.lora is not None:
        task_args.lora.model = check_and_download_model_by_name(
            task_args.lora.model,
            LoraLoaderMixin.lora_state_dict,
            **kwargs
        )

    if task_args.textual_inversion is not None:
        task_args.textual_inversion = check_and_download_model_by_name(
            task_args.textual_inversion,
            load_textual_inversion_state_dicts,
            **kwargs
        )


def check_and_download_model_by_name(
        model_name: str,
        loader_fn: Callable,
        **kwargs) -> str:
    hf_cache_dir = kwargs.pop("hf_cache_dir")
    external_cache_dir = kwargs.pop("external_cache_dir")
    proxy = kwargs.pop("proxy")

    if validators.url(model_name):
        return check_and_download_external_model(model_name, external_cache_dir, proxy)
    else:
        return check_and_download_hf_model(model_name, loader_fn, hf_cache_dir, proxy)


def check_and_download_external_model(
        model_name: str,
        external_cache_dir: str,
        proxy: ProxyConfig | None
) -> str:

    print("Check and download the external model file: " + model_name)

    m = hashlib.sha256()
    m.update(model_name.encode('utf-8'))
    url_hash = m.hexdigest()

    model_folder = os.path.join(external_cache_dir, url_hash)
    model_file = os.path.join(model_folder, "model.safetensors")

    print("The model file will be saved as: " + model_file)

    # Check if we have already cached the model file
    if os.path.isdir(model_folder):
        if os.path.isfile(model_file):
            print("Found a local cache of the model file. Skip the download")
            return model_file
    else:
        os.mkdir(model_folder, 0o755)

    # Download the model file
    model_file = os.path.join(model_folder, "model.safetensors")

    print("Model file not cached locally. Start the download...")

    try:
        if proxy.host != "":
            proxy_str = proxy.host + ":" + str(proxy.port)

            print("Download using proxy: " + proxy_str)

            default_headers = None
            if proxy.username != "" and proxy.password != "":
                default_headers = urllib3.make_headers(proxy_basic_auth=proxy.username + ':' + proxy.password)
            http = urllib3.ProxyManager(
                proxy_str,
                proxy_headers=default_headers,
                num_pools=1
            )
        else:
            http = urllib3.PoolManager(num_pools=1)

        resp = http.request("GET", model_name, preload_content=False)
        total_bytes = resp.getheader("content-length", None)
        if total_bytes is not None:
            total_bytes = int(total_bytes)

        with tqdm.wrapattr(open(model_file, "wb"), "write",
                           miniters=1, desc=model_file,
                           total=total_bytes) as f_out:
            for chunk in resp.stream(1024):
                if chunk:
                    f_out.write(chunk)
            f_out.flush()

        return model_folder
    except Exception as e:
        # delete the broken file if download failed
        if os.path.isfile(model_file):
            os.remove(model_file)

        raise e


def check_and_download_hf_model(
        model_name: str,
        loader_fn: Callable,
        hf_cache_dir: str,
        proxy: ProxyConfig | None
) -> str:
    print("Check and download the Huggingface model file: " + model_name)

    call_args = {
        "proxy": get_hf_proxy_dict(proxy),
        "cache_dir": hf_cache_dir,
        "torch_dtype": torch.float16,
        "resume_download": True,
    }

    loader_fn(model_name, **call_args)

    return model_name


def get_hf_proxy_dict(proxy: ProxyConfig | None) -> dict | None:
    if proxy is not None and proxy.host != "":

        proxy_str = proxy.host + ":" + str(proxy.port)

        return {
            'https': proxy_str,
            'http': proxy_str
        }
    else:
        return None