#!/bin/bash -l
# This file comes from the utilities you're using to run a singularity script on HPC.
# It is copied to iris-cluster:$SCRATCH/iris_singularity_tools as part of the normal operation of the script.
# You can safely delete it since it's recreated when needed
set -e

INSTANCE=$0

module load tools/Singularity
command="singularity shell [ARGUMENTS]"
$command