# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Calculate quality metrics for previous training run or pretrained network pickle."""

"""
To run the script:

CUDA_VISIBLE_DEVICES=0, python /home/matteolai/diciotti/matteo/Synthetic_Images_Metrics_Toolkit/calc_metrics_PACGAN.py \
    --network /home/matteolai/diciotti/matteo/GAN_metrics/utils_networks/generator_best.pt \
    --json_path /home/matteolai/diciotti/matteo/GAN_metrics/utils_networks/config.json \
    --metrics fid50k,kid50k,pr50k3 \
    --data /home/matteolai/diciotti/data/ADNI/ADNI_train/PACGAN/Real256x256.nii.gz \
    --labels /home/matteolai/diciotti/data/ADNI/ADNI_train/PACGAN/labels.csv \
    --gpus 1 \
    --verbose True

pr50k3,pr_auth
"""


import os
import click
import json
import tempfile
import copy
import torch
import dnnlib

import legacy
from metrics import metric_main
from metrics import metric_utils
from torch_utils import training_stats
from torch_utils import custom_ops
from torch_utils import misc

from utils_networks.model import Generator

import sys
if not sys.warnoptions:
    import warnings 
    warnings.filterwarnings("ignore")

#----------------------------------------------------------------------------

def subprocess_fn(rank, args, temp_dir):
    dnnlib.util.Logger(should_flush=True)

    # Init torch.distributed.
    if args.num_gpus > 1:
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

    # Print network summary.
    device = torch.device('cuda', rank)
    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    G = copy.deepcopy(args.G).eval().requires_grad_(False).to(device)
    if rank == 0 and args.verbose:
        z = torch.empty([1, G.z_dim], device=device)
        c = torch.empty([1, G.c_dim], device=device)
        misc.print_module_summary(G, [z, c])

    # Calculate each metric.
    for metric in args.metrics:
        if rank == 0 and args.verbose:
            print(f'Calculating {metric}...')
        progress = metric_utils.ProgressMonitor(verbose=args.verbose)
        result_dict = metric_main.calc_metric(metric=metric, G=G, dataset_kwargs=args.dataset_kwargs,
            num_gpus=args.num_gpus, rank=rank, device=device, progress=progress)
        if rank == 0:
            metric_main.report_metric(result_dict, run_dir=args.run_dir, snapshot_pkl=args.network_pkl)
        if rank == 0 and args.verbose:
            print()

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
@click.option('network_path', '--network', help='Network pickle filename or URL', metavar='PATH', required=True)
@click.option('json_path', '--json_path', help='Path to the JSON file', metavar='PATH', required=True)
@click.option('--metrics', help='Comma-separated list or "none"', type=CommaSeparatedList(), default='fid50k_full', show_default=True)
@click.option('--data', help='Dataset to evaluate metrics against (directory or zip) [default: same as training data]', metavar='PATH')
@click.option('--labels', help='Labels of the dataset to evaluate metrics against (directory or zip) [default: same as training data]', metavar='PATH')
@click.option('--mirror', help='Whether the dataset was augmented with x-flips during training [default: look up]', type=bool, metavar='BOOL')
@click.option('--gpus', help='Number of GPUs to use', type=int, default=1, metavar='INT', show_default=True)
@click.option('--verbose', help='Print optional information', type=bool, default=True, metavar='BOOL', show_default=True)

def calc_metrics(ctx, network_path, json_path, metrics, data, labels, mirror, gpus, verbose):
    """Calculate quality metrics for previous training run or pretrained network pickle.

    Examples:

    \b
    # Previous training run: look up options automatically, save result to JSONL file.
    python calc_metrics.py --metrics=pr50k3_full \\
        --network=~/training-runs/00000-ffhq10k-res64-auto1/network-snapshot-000000.pkl

    \b
    # Pre-trained network pickle: specify dataset explicitly, print result to stdout.
    python calc_metrics.py --metrics=fid50k_full --data=~/datasets/ffhq.zip --mirror=1 \\
        --network=https://nvlabs-fi-cdn.nvidia.com/stylegan2-ada-pytorch/pretrained/ffhq.pkl

    Available metrics:

    \b
      ADA paper:
        fid50k_full  Frechet inception distance against the full dataset.
        kid50k_full  Kernel inception distance against the full dataset.
        pr50k3_full  Precision and recall againt the full dataset.
        is50k        Inception score for CIFAR-10.

    \b
      StyleGAN and StyleGAN2 papers:
        fid50k       Frechet inception distance against 50k real images.
        kid50k       Kernel inception distance against 50k real images.
        pr50k3       Precision and recall against 50k real images.
        ppl2_wend    Perceptual path length in W at path endpoints against full image.
        ppl_zfull    Perceptual path length in Z for full paths against cropped image.
        ppl_wfull    Perceptual path length in W for full paths against cropped image.
        ppl_zend     Perceptual path length in Z at path endpoints against cropped image.
        ppl_wend     Perceptual path length in W at path endpoints against cropped image.
    
    \b 
      Extra metrics:
        pr_auth    alpha-Precision, beta-Recall and authenticity 
    
    """
    dnnlib.util.Logger(should_flush=True)

    # Validate arguments.
    args = dnnlib.EasyDict(metrics=metrics, num_gpus=gpus, network_pkl=network_path, verbose=verbose)
    if not all(metric_main.is_valid_metric(metric) for metric in args.metrics):
        ctx.fail('\n'.join(['--metrics can only contain the following values:'] + metric_main.list_valid_metrics()))
    if not args.num_gpus >= 1:
        ctx.fail('--gpus must be at least 1')

    # Read parameters
    with open(json_path) as f:
        config_data = json.load(f)
    args.z_dim = config_data["Z_DIM"]; 
    embedding_dim = config_data["EMBEDDING_DIM"]
    args.c_dim = config_data["CLASS_SIZE"]
    img_channels = config_data["IMAGE_CHANNELS"]
    in_channels = config_data["IN_CHANNELS"]
    factors = eval(config_data["FACTORS"])

    # Load network.
    if not dnnlib.util.is_url(network_path, allow_file_urls=True) and not os.path.isfile(network_path):
        ctx.fail('--network must point to a file or URL')
    if args.verbose:
        print(f'Loading network from "{network_path}"...')
    network_dict = torch.load(network_path, map_location='cpu')['model_state_dict']
    args.G = Generator(args.z_dim, embedding_dim, args.c_dim, img_channels, in_channels, factors)
    args.G.load_state_dict(network_dict)

    # Initialize dataset options.
    if data is not None:
        # args.dataset_kwargs = dnnlib.EasyDict(class_name='PACGAN_utils.Load_dataset.LoadDataset', path=data, path_labels=labels)
        args.dataset_kwargs = dnnlib.EasyDict(class_name='training.dataset_NIfTI_PACGAN.ImageFolderDataset', path=data, path_labels=labels)#, use_labels=True)

    elif network_dict['training_set_kwargs'] is not None:
        args.dataset_kwargs = dnnlib.EasyDict(network_dict['training_set_kwargs'])
    else:
        ctx.fail('Could not look up dataset options; please specify --data')

    # Finalize dataset options.
    args.dataset_kwargs.resolution = args.G.img_resolution
    args.dataset_kwargs.use_labels = (args.G.c_dim != 0)
    if mirror is not None:
        args.dataset_kwargs.xflip = mirror

    # Print dataset options.
    if args.verbose:
        print('Dataset options:')
        print(json.dumps(args.dataset_kwargs, indent=2))

    # Locate run dir.
    args.run_dir = None
    print(os.path.join(os.path.dirname(network_path), 'training_options.json'))
    if os.path.isfile(network_path):
        pkl_dir = os.path.dirname(network_path)
        print(os.path.join(pkl_dir, 'training_options.json'))
        if os.path.isfile(os.path.join(pkl_dir, 'training_options.json')):
            args.run_dir = pkl_dir

    # Launch processes.
    if args.verbose:
        print('Launching processes...')
    torch.multiprocessing.set_start_method('spawn')
    with tempfile.TemporaryDirectory() as temp_dir:
        if args.num_gpus == 1:
            subprocess_fn(rank=0, args=args, temp_dir=temp_dir)
        else:
            torch.multiprocessing.spawn(fn=subprocess_fn, args=(args, temp_dir), nprocs=args.num_gpus)

#----------------------------------------------------------------------------

if __name__ == "__main__":
    calc_metrics() # pylint: disable=no-value-for-parameter

#----------------------------------------------------------------------------
