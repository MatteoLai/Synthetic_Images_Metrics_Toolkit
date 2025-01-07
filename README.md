<!--
SPDX-FileCopyrightText: 2024 Matteo Lai <matteo.lai3@unibo.it>

SPDX-License-Identifier: NPOSL-3.0
-->

[<img src="https://img.shields.io/badge/  -Dockerhub-blue.svg?logo=docker&logoColor=white">](<https://hub.docker.com/r/aiformedresearch/metrics_toolkit>) 

# Synthetic_Images_Metrics_Toolkit

This repository provides a comprehensive collection of state-of-the-art metrics for evaluating the quality of synthetic images. 
These metrics enable the assessment of:
- Fidelity: the realism of synthetic data;
- Diversity: the coverage of the real data distribution;
- Generalizability: the generation of authentic, non-memorized images. 

<p align="center">
  <img src="Images/Metrics.png" width="400" title="metrics">
</p>


## Licenses
This repository complies with the [REUSE Specification](https://reuse.software/). All source files are annotated with SPDX license identifiers, and full license texts are included in the `LICENSES` directory.

### Licenses Used

1. **LicenseRef-NVIDIA-1.0**: Applies to code reused from NVIDIA's StyleGAN2 repository: https://github.com/NVlabs/stylegan2-ada-pytorch, under the [NVIDIA Source Code License](https://nvlabs.github.io/stylegan2-ada-pytorch/license.html).
2. **MIT**:  For code reused from:
    - https://github.com/vanderschaarlab/evaluating-generative-models; 
    - https://github.com/clovaai/generative-evaluation-prdc.
3. **BSD-3-Clause**: Applies to two scripts reused from https://github.com/vanderschaarlab/evaluating-generative-models;
4. **NPOSL-3.0**: Applies to the code developed specifically for this repository.

For detailed license texts, see the `LICENSES` directory.

## Installation
Before proceeding, ensure that [CUDA](https://developer.nvidia.com/cuda-downloads) is installed. CUDA 11.0 or later is recommended, though newer versions may produce warnings.

### Installation with Anaconda
0. Install [Anaconda](https://docs.anaconda.com/free/anaconda/install/index.html) for your operating system.
1. Create a Conda environment and install the required dependencies using the following commands:
    ```
    conda create -n metrics_toolkit python=3.7 -y
    conda activate metrics_toolkit
    pip install -r requirements.txt
    ```

### Installation with Docker
0. Install [Docker](https://docs.docker.com/get-docker/) for your operating system.

1. Pull the Docker image
    ```
    docker pull aiformedresearch/metrics_toolkit
    ```

2. Run the Docker container
    ```
    docker run -it --gpus all aiformedresearch/pacgan \
      -v /absolute/path/to/real_data.nii.gz:/Metrics_Toolkit/data \
      -v /absolute/path/to/pretrained_network_file:/Metrics_Toolkit/data \
      -v /absolute/path/to/local_output_directory:/Metrics_Toolkit/outputs \
      aiformedresearch/metrics_toolkit
    ```
      - The `--gpus all` flag enables GPU support. Specify a GPU if needed, e.g., `--gpus 0`.
      - The `-v` flag is used to mount the local directories to the working directory `Metrics_Toolkit` inside the container. 
      > Note: To exit from the Docker container, type: `exit`.

Refer to the [Usage](#usage) section for detailed instructions about running the main script. 


## Usage
### 1. Customize for your use case
To evaluate your generative model, you need to modify the `calc_metrics_demo.py` script in the three points underlined by the "Demo" comment. Specifically:
1. Import the generator class
    ```
    # Example:

    from utils_networks.model import Generator
    ```
2. Define the generative model
    ```
    # Example:

    args.G = Generator(args.z_dim, embedding_dim, args.c_dim, img_channels, in_channels, factors)
    args.G.load_state_dict(network_dict)
    ```
3. Specify the dataset class. Replace `XXXXX_to_be_replaced_XXXXX` with the actual class name:
    ```
    # Example:

    args.dataset_kwargs = dnnlib.EasyDict(class_name='XXXXX_to_be_replaced_XXXXX', path=data, path_labels=labels)
    ```
    
    For the dataset class definition, provided script include:
    - [dataset.py](training/dataset.py): original version of the dataset from the [StyleGAN2-ADA repository](https://github.com/NVlabs/stylegan2-ada-pytorch), handling PNG images;
    - [dataset_NIfTI.py](training/dataset_NIfTI.py): adapted for NIfTI files with shape `[img_res, img_res, #channels, #images]`. `img_res` is the image resolution, `#channels` is the number of channels (1 for grayscale images), and `#images` is the number of real images in the NIfTI file.

This system has been tested on:
- [PACGAN](https://github.com/MatteoLai/PACGAN), a custom generative adversarial network  (`calc_metrics_PACGAN.py`) 
- [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch) (`calc_metrics_StyleGAN.py`)

*Future releases will simplify customization through a JSON configuration file.*

### 2. Run the script
Once customized, execute the main script with:
```
python calc_metrics.py \
  --network /path_to/pretrained_network.pkl \
  --metrics fid50k_full,kid50k_full,pr50k3_full,ppl_zfull,pr_auth,prdc50k,knn \
  --data /path_to/real_data.nii.gz" \
  --run_dir /path_to/output_dir/
```

This command evaluates the synthetic images generated by the pre-trained generative model indicated in `--network`, against the real images indicated in `--data`. Metrics results are saved in the `--run_dir` directory. The complete set of metrics that you can indicate in the `--metrics` flag is listed in the following sections: [Quantitative metrics](#quantitative-metrics) and [Qualitative metrics](#qualitative-metrics).

By default the script will compute the metrics between all the real images and 50,000 synthetic ones, but it is possible to set the number of generated images with the `--num_gen` flag.

## Metrics overview
### Quantitative metrics
The following quantitative metrics are available:

| Metric flag      | Description | Original implementation |
| :-----        | :-----: | :---------- |
| `fid50k_full` | Fr&eacute;chet inception distance<sup>[1]</sup> against the full dataset | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `kid50k_full` | Kernel inception distance<sup>[2]</sup> against the full dataset         | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `pr50k3_full` | Precision and recall<sup>[3]</sup> againt the full dataset               | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `is50k`       | Inception score<sup>[4]</sup> for CIFAR-10                               | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `ppl2_wend`   |  Perceptual path length<sup>[5]</sup> in W, endpoints, full image        | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `ppl_zfull`   |  Perceptual path length in Z, full paths, cropped image                  | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `ppl_wfull`   |  Perceptual path length in W, full paths, cropped image                  | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `ppl_zend`    | Perceptual path length in Z, endpoints, cropped image                    | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `ppl_wend`    |  Perceptual path length in W, endpoints, cropped image                   | [StyleGAN2-ADA](https://github.com/NVlabs/stylegan2-ada-pytorch)
| `prdc`    |  Precision, recall, density, and coverage<sup>[6]</sup>                      | [prdc](https://github.com/clovaai/generative-evaluation-prdc)
| `pr_auth`    |  	$\alpha$-precision, 	$\beta$-recall, and authenticity<sup>[7]</sup>   | [evaluating-generative-models](https://github.com/vanderschaarlab/evaluating-generative-models)

References:
1. [GANs Trained by a Two Time-Scale Update Rule Converge to a Local Nash Equilibrium](https://arxiv.org/abs/1706.08500), Heusel et al. 2017
2. [Demystifying MMD GANs](https://arxiv.org/abs/1801.01401), Bi&nacute;kowski et al. 2018
3. [Improved Precision and Recall Metric for Assessing Generative Models](https://arxiv.org/abs/1904.06991), Kynk&auml;&auml;nniemi et al. 2019
4. [Improved Techniques for Training GANs](https://arxiv.org/abs/1606.03498), Salimans et al. 2016
5. [A Style-Based Generator Architecture for Generative Adversarial Networks](https://arxiv.org/abs/1812.04948), Karras et al. 2018
6. [Reliable Fidelity and Diversity Metrics for Generative Models](https://proceedings.mlr.press/v119/naeem20a/naeem20a.pdf), Naeem et al., 2020
7. [How Faithful is your Synthetic Data?
Sample-level Metrics for Evaluating and Auditing Generative Models](https://proceedings.mlr.press/v162/alaa22a/alaa22a.pdf), Alaa et al., 2022

### Qualitative metrics
| Metric flag      | Description | Original implementation |
| :-----        | :-----: | :---------- |
| `knn` | k-nearest neighbors (k-NN) analysis, to assess potential memorization of the model | Custom implementation |

<p align="center">
  <img src="Images/knn_analysis.png" width="600" title="knn-analysis">
</p>

The k-NN analysis identifies and visualizes the `top_n` real images most similar to any synthetic sample (from a set of 50,000 generated samples). For each real image, the visualization displays the top `k` synthetic images ranked by their cosine similarity to the corresponding real image.

By default, `k=5` and `top_n=3`. These parameters can be adjusted in the `knn` function within the [metric_main.py](metrics/metric_main.py) file.

## To do list
☐ Test metrics on diffusion models

☐ Enable parameter configuration via JSON file 

## Aknowledgments
This repository builds on NVIDIA's StyleGAN2-ADA repository: https://github.com/NVlabs/stylegan2-ada-pytorch.
