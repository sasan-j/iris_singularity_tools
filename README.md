# Running Docker containers on HPC

## uni.lu HPC

These tools assume that you already have an HPC account and access to the iris-cluster.

The following `~/.ssh/config` is assumed:

```
Host iris-cluster
    Hostname access-iris.uni.lu
    Port 8022
    User <your_hpc_username>
    IdentityFile ~/.ssh/keys/id_hpc_uni_lu
Host iris-0*
    ProxyJump iris-cluster
    User <your_hpc_username>
    IdentityFile ~/.ssh/keys/id_hpc_uni_lu
Host iris-1*
    ProxyJump iris-cluster
    User <your_hpc_username>
    IdentityFile ~/.ssh/keys/id_hpc_uni_lu
```

This should allow you to `ssh iris-cluster` without error.

For more information about accessing the uni.lu hpc, see the [official documentation](https://hpc.uni.lu).

## Preliminary Concepts

### Singularity

Since docker container often (but not always) run as "root", allowing a user to use docker on a machine essentially gives him "sudo" privilege.
This is unacceptable on machines that are shared with constraints between many users such as HPC platforms, so these resort to a different alternative such as Singularity.
Singularity works without root privileges by running container as the current user, and therefore does not require special privileges.

### Building a Singularity image (SIF file)

Building Docker containers usually involves root access, it cannot be done directly on the HPC platform. Rather, you should

1. _Build_ your Docker image on your local machine with root access
2. Export your Docker image as a tar file and transfer it to the HPC platform
3. Convert your Docker image into a Singularity compatible image on the HPC platform
4. Reserve resources and run your Singularity image on the HPC

Our script covers all these steps for you, you only need to build your Docker image locally and transfer it over to HPC using the `docker-convert` subcommand.

```bash
./iris_singularity_tools.py docker-convert --tag <tag> --sif-path /path/on/iris/for/image.sif
```

You can also use the same subcommand to convert an existing image from an online registry like DockerHub.

```bash
./iris_singularity_tools.py docker-convert --source=registry --tag <tag> --sif-path /path/on/iris/for/image.sif
```

## Attaching VSCode to develop on HPC

### Initial Setup

Attaching VSCode to a Singularity container requires the use of VSCode Insiders (as of September 2022). In addition, you should install the remote SSH extension, and enable the following settings:

```json
{
  "remote.SSH.enableRemoteCommand": true,
  "remote.SSH.useLocalServer": true
}
```

### Attaching VSCode

Attaching VSCode to a remote Singularity container is not supported by default, but our `attach-vscode` subcommand should make it easy by automating the following steps:

- Resource allocation (cpus, gpus, memory, allocated time, ...)
- Configure your local SSH to connect directly to the allocated node and start the Singularity container

The subcommand `--help` will show all available customization options, but here is a short example:

```
./iris_singularity_tools.py attach-vscode --job-name awesome-project --time 01:00:00 --cpus 7 --gpus 1 --mem 32G --singularity-image /path/to/image.sif
```

This command will automatically update your SSH config to include a host corresponding to the given job name, in our example the host `awesome-project-vscode` will be created. This can be used to easily attach VSCode for as long as the node remains allocated.

If things are working correctly after attaching to the remote, opening an integrated terminal in VSCode should give your a prompt that starts with `Singularity >`, proving that you are inside the Singularity image. You should now be able to enjoy all the dev features from VSCode as-if you were developing locally, including code analysis, autocompletions, debuggers, integrated jupyter notebooks, _etc._

## Running a job on HPC

### Starting a job

The `run` subcommand can be used to quickly start a job in a Singularity image. The full list of options can be displayed using `./iris_singularity_tools.py run --help`. Here is an example:

```bash
./iris_singularity_tools.py run --job-name test --singularity-image /path/to/image.sif --time "00:10:00" --cpus 2 --gpus 1 --mem 8G command_to_run --command_arg1 --command_arg2 arg3
```

By default, the job is queued instantly using `srun` and the command waits for resources to be available. If you want to queue the job and return immediately using `sbatch`, you can add the `--batch` option.

### Baby-sitting your jobs

1. Listing your jobs: `squeue --me --states=all`
2. Canceling a job by its id or its name: `scancel 1234`, `scancel --name <jobname>`
3. Monitoring a job's output while it's running: `tail -f <jobname>-<jobid>.out`
