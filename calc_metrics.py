# SPDX-License-Identifier: LicenseRef-NVIDIA-1.0
#
# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.


import os
import click
import tempfile
import torch
import dnnlib

from metrics import metric_main
from metrics import metric_utils
from torch_utils import training_stats
from torch_utils import custom_ops

import importlib 
from metrics.create_report import generate_metrics_report

import sys
if not sys.warnoptions:
    import warnings 
    warnings.filterwarnings("ignore")

#----------------------------------------------------------------------------

def load_config_from_path(config_path):
    """Dynamically loads a config.py file from the given path."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found at {config_path}")
    
    spec = importlib.util.spec_from_file_location("config", config_path)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    
    return config

#----------------------------------------------------------------------------

def print_config(config):
    """Prints the loaded configuration in a readable format."""
    print("\nLoaded Configuration:")
    print(f"  METRICS: {config.METRICS}")
    print("\n  CONFIGS:")
    for key, value in config.CONFIGS.items():
        print(f"    {key}: {value}")
    print("\n  METRICS_CONFIGS:")
    for key, value in config.METRICS_CONFIGS.items():
            print(f"    {key}: {value}")
    print("\n  SYNTHETIC_DATA:")
    mode = "pretrained_model" if config.USE_PRETRAINED_MODEL else "from_files",
    print("  mode: ", mode)
    for key, value in config.SYNTHETIC_DATA[mode[0]].items():
        print(f"      {key}: {value}")
    print("\n  DATASET:")
    for key, value in config.DATASET.items():
        print(f"    {key}: {value}")
    print()

#----------------------------------------------------------------------------

def get_module_path(file_path):
    # Normalize the path
    normalized_path = os.path.normpath(file_path)
    base_dir = os.path.normpath(os.getcwd())

    # Find the relative path
    normalized_path = os.path.relpath(normalized_path, base_dir)

    # Remove the file extension
    root, _ = os.path.splitext(normalized_path)

    # Replace directory separators with dots
    module_path = root.replace(os.sep, '.')

    return module_path

#----------------------------------------------------------------------------

def subprocess_fn(rank, args, temp_dir):
    dnnlib.util.Logger(should_flush=True)
    # define device
    device = torch.device(f'cuda:{rank}' if torch.cuda.is_available() and args.num_gpus > 0 else 'cpu')

    # Init torch.distributed.
    if args.num_gpus > 1 and torch.cuda.is_available():
        init_file = os.path.abspath(os.path.join(temp_dir, '.torch_distributed_init'))
        if os.name == 'nt':
            init_method = 'file:///' + init_file.replace('\\', '/')
            torch.distributed.init_process_group(backend='gloo', init_method=init_method, rank=rank, world_size=args.num_gpus)
        else:
            init_method = f'file://{init_file}'
            torch.distributed.init_process_group(backend='nccl', init_method=init_method, rank=rank, world_size=args.num_gpus)

    # Init torch_utils.
    sync_device = torch.device('cuda', rank) if args.num_gpus > 1 else None
    training_stats.init_multiprocessing(rank=rank, sync_device=sync_device)
    if rank != 0 or not args.verbose:
        custom_ops.verbosity = 'none'

    if torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False

    # Visualize one sample for real and generated data
    if rank == 0:
        metric_utils.visualize_ex_samples(args, device=device, rank=rank, verbose=args.verbose)

    # Calculate each metric.
    for metric in args.metrics:
        if rank == 0 and args.verbose:
            print(f'Calculating {metric}...')
        progress = metric_utils.ProgressMonitor(verbose=args.verbose)

        # Set the path to the OC detector:
        train_OC = False if args.oc_detector_path is not None else True
        oc_detector_path = args.oc_detector_path if args.oc_detector_path is not None else args.run_dir+'/oc_detector.pkl'
        
        result_dict = metric_main.calc_metric(
            metric=metric,
            use_pretrained_generator=args.use_pretrained_generator,
            run_generator=args.run_generator, 
            num_gen=args.num_gen, 
            nhood_size = args.nhood_size,
            knn_configs = args.knn_configs,
            padding = args.padding,
            oc_detector_path=oc_detector_path, 
            train_OC=train_OC, 
            snapshot_pkl=args.network_path, 
            run_dir=args.run_dir, 
            G=args.G, 
            dataset_kwargs=args.dataset_kwargs,
            dataset_synt_kwargs=args.dataset_synt_kwargs,
            num_gpus=args.num_gpus, 
            rank=rank, device=device, 
            progress=progress
            )
        if rank == 0:
            synt_source = args.network_path if args.use_pretrained_generator else args.dataset_synt_kwargs['path_data']
            metric_main.report_metric(result_dict, run_dir=args.run_dir, synt_source=synt_source)
        if rank == 0 and args.verbose:
            print()

    # Create the final report.
    generate_metrics_report(args)

    # Done.
    if rank == 0 and args.verbose:
        print('Exiting...')

#----------------------------------------------------------------------------

class CommaSeparatedList(click.ParamType):
    name = 'list'

    def convert(self, value, param, ctx):
        _ = param, ctx
        if value is None or value.lower() == 'none' or value == '':
            return []
        return value.split(',')

#----------------------------------------------------------------------------

@click.command()
@click.pass_context
@click.option('--config', help='Path to config.py', metavar='PATH', required=True)

def calc_metrics(ctx, config):

    dnnlib.util.Logger(should_flush=True)

    # Load configuration dynamically
    config_path=config
    print(f"Reading configuration from {config_path}...")
    config = load_config_from_path(config_path)

    # Validate configuration
    metric_utils.validate_config(config)

    args = dnnlib.EasyDict({
        'metrics': config.METRICS,
        'run_dir': config.CONFIGS["RUN_DIR"],
        'knn_configs': config.METRICS_CONFIGS["K-NN_configs"],
        'nhood_size': config.METRICS_CONFIGS["nhood_size"],
        'padding': config.METRICS_CONFIGS["padding"],
        'num_gpus': config.CONFIGS["NUM_GPUS"],
        'verbose': config.CONFIGS["VERBOSE"],
        'oc_detector_path': config.CONFIGS["OC_DETECTOR_PATH"],
        'num_gen': config.SYNTHETIC_DATA["pretrained_model"]["NUM_SYNTH"] if config.USE_PRETRAINED_MODEL else config.SYNTHETIC_DATA["from_files"]["params"]["size_dataset"],
        'network_path': config.SYNTHETIC_DATA["pretrained_model"]["network_path"] if config.USE_PRETRAINED_MODEL else None,
        'load_network': config.SYNTHETIC_DATA["pretrained_model"]["load_network"] if config.USE_PRETRAINED_MODEL else None,
        'run_generator': config.SYNTHETIC_DATA["pretrained_model"]["run_generator"] if config.USE_PRETRAINED_MODEL else None,
        'dataset_synt': config.SYNTHETIC_DATA["from_files"] if not config.USE_PRETRAINED_MODEL else None,
        'dataset': config.DATASET,
        'use_pretrained_generator': config.USE_PRETRAINED_MODEL,
        'config_path': config_path
    })

    # Print configuration values
    if args.verbose:
        print_config(config)

    # Load the pre-trained generator
    if args.use_pretrained_generator:
        if args.verbose:
            print(f'Loading network from "{args.network_path}"...')
        args.G = args.load_network(args.network_path)
        args.dataset_synt_kwargs = None
    else:
        args.G = None
        if args.dataset_synt["params"]["path_data"] is not None:
            args.dataset_synt_kwargs = dnnlib.EasyDict(
                class_name=get_module_path(args.config_path)+"."+args.dataset_synt["class"].__name__,
                **args.dataset_synt["params"]
                    )
        else:
            ctx.fail('Could not look up dataset options; please specify DATASET configurations from the configuration file.')

    # Initialize dataset options.
    if args.dataset['params']['path_data'] is not None:
        args.dataset_kwargs = dnnlib.EasyDict(
            class_name=get_module_path(args.config_path)+"."+args.dataset["class"].__name__,
            **args.dataset["params"]
                )
    else:
        ctx.fail('Could not look up dataset options; please specify DATASET configurations from the configuration file.')

    if args.verbose:
        print('Launching processes...')
    torch.multiprocessing.set_start_method('spawn', force=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        if args.num_gpus <= 1:
            if args.num_gpus==0:
                print("Running in CPU mode...")
            else:
                print("Running in single GPU mode...")
            subprocess_fn(rank=0, args=args, temp_dir=temp_dir)
        else:
            print(f"Spawning {args.num_gpus} processes...")
            torch.multiprocessing.spawn(fn=subprocess_fn, args=(args, temp_dir), nprocs=args.num_gpus)

#----------------------------------------------------------------------------

if __name__ == "__main__":
    calc_metrics() # pylint: disable=no-value-for-parameter

#----------------------------------------------------------------------------
