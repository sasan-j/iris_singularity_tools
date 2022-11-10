#!/usr/bin/env python3

from argparse import ArgumentParser, REMAINDER
from cmath import sin
from pathlib import Path
from typing import List
import subprocess
import os
import sys
from datetime import datetime
from logger import get_logger

L = get_logger(Path(__file__).name.replace(".py", ""))


def die(msg: str, ex: Exception = None):
    L.error(msg, exc_info=ex)
    sys.exit(-1)


try:
    import sshconf
except ModuleNotFoundError:
    print(f"sshconf module not found. Attempting to install it for you...")
    subprocess.run(["pip3", "install", "sshconf"], check=True)
    import sshconf

from dataclasses import dataclass


@dataclass
class SallocArgs:
    job_name: str
    time: str
    cpus: int
    gpus: int
    mem: str
    slurm_args: List[str]
    volta32: bool

    @staticmethod
    def add_args_to_parser(parser: ArgumentParser):
        parser.add_argument("--job-name", type=str, required=True, help="A name for your SLURM job")
        parser.add_argument(
            "--time",
            type=str,
            required=True,
            help="Time to reserve resources for. Example for 1h: '01:00:00'. See SLURM doc for formatting.",
        )
        parser.add_argument("--cpus", type=int, required=True, help="Number of CPU cores to reserve.")
        parser.add_argument("--mem", type=str, required=True, help="RAM to reserve (eg. '16G')")
        parser.add_argument("--gpus", type=int, required=True, help="Number of GPUs to reserve. 0 for no GPUs.")
        parser.add_argument(
            "--slurm-arg",
            action="append",
            default=[],
            help="Additional SLURM argument to use. Can be repeated to add more arguments.",
        )
        parser.add_argument(
            "--volta32",
            action="store_true",
            help="If specified, will reserve a 32GB V100 GPU (use only if needed, allocation is often slower on these).",
        )

    @staticmethod
    def from_args(args):
        return SallocArgs(args.job_name, args.time, args.cpus, args.gpus, args.mem, args.slurm_arg, args.volta32)


@dataclass
class SingularityArgs:
    singularity_image: str
    singularity_args: List[str]
    singularity_env: List[str]

    @staticmethod
    def add_args_to_parser(parser: ArgumentParser):
        parser.add_argument(
            "--singularity-image",
            type=str,
            help="The path on the iris cluster to the Singularity image to run (eg. SIF file). To obtain a SIF file from a docker image use the `convert-docker` subcommand.",
            required=True,
        )
        parser.add_argument(
            "--singularity-arg",
            action="append",
            default=[],
            help="Additional Singularity arguments (eg. --env). Can be repeated to add more arguments.",
        )
        parser.add_argument(
            "--singularity-env",
            action="append",
            default=[],
            help="Specific environment variables to override in Singularity container. Format is 'MYVAR=value'. Can be repeated to add more than one.",
        )

    @staticmethod
    def from_args(args):
        return SingularityArgs(args.singularity_image, args.singularity_arg, args.singularity_env)


def exec_output_sync(command: List[str], exec_on_iris: bool) -> str:
    if exec_on_iris and not on_iris():
        command = ["ssh", "iris-cluster"] + command
    bytes = subprocess.check_output(command)
    return bytes.decode("utf-8").strip()


def on_iris() -> bool:
    return "iris-" in exec_output_sync(["hostname"], exec_on_iris=False)


def get_iris_username() -> bool:
    return exec_output_sync(["whoami"], exec_on_iris=True)


def exec(command: List[str], exec_on_iris: bool, echo_command: bool = True, check=True, force_tty=False, **kwargs):
    command = [str(x) for x in command]
    if exec_on_iris and not on_iris():
        tty = ["-t"] if force_tty else []
        command = ["ssh"] + tty + ["iris-cluster"] + command
    if echo_command:
        print(join_str(command))
    return subprocess.run(command, check=check, **kwargs)


def copy_to_iris(path: Path, iris_destination_path: Path):
    if on_iris():
        exec(["/bin/cp", "-fR", str(path), str(iris_destination_path)])
    else:
        exec(["scp", path, f"iris-cluster:{iris_destination_path}"], exec_on_iris=False)


def join_str(l: List, x: str = " "):
    return x.join([str(x) for x in l])


def prepare_slurm_and_singularity_args(salloc: SallocArgs, singularity: SingularityArgs):
    alloc_args = [
        f"-c",
        salloc.cpus,
        f"--time={salloc.time}",
        f"--mem={salloc.mem}",
        "-J",
        salloc.job_name,
    ] + salloc.slurm_args
    if salloc.gpus > 0:
        gpu_capability = "gpu,volta32" if salloc.volta32 else "gpu"
        alloc_args += ["-p", "gpu", "-G", salloc.gpus, "-C", gpu_capability]
    singularity_args = singularity.singularity_args
    if args.gpus > 0 and "--nv" not in singularity_args:
        singularity_args += ["--nv"]
    if len(args.singularity_env) > 0:
        singularity_args += [f"--env {env_var}" for env_var in singularity.singularity_env]
    return alloc_args, singularity_args


def scratch_path():
    username = get_iris_username()
    return Path(f"/scratch/users/{username}")


def tools_path():
    return scratch_path() / Path(__file__).name.replace(".py", "")


def copy_to_tools_folder(path: Path, name: str):
    folder = tools_path()
    exec(["mkdir", "-p", str(folder)], exec_on_iris=True)
    copy_to_iris(path, folder / name)
    return folder / name

def get_allocated_node_by_jobname(job_name: str):
    allocated_nodes = exec_output_sync(
        ["squeue", "--me", "-h", f'--name="{job_name}"', "-o", '"%R"'], exec_on_iris=True
    ).split("\n")
    if len(allocated_nodes) > 1:
        L.warning(
            f"Detected several allocations with name '{job_name}'. You probably want to kill some of them to avoid wasting resources. Use `squeue --me` on iris-cluster to decide which allocations to use `scancel` on"
        )
    return allocated_nodes[0]


def copy_vscode_attach_script_to_tools(job_name: str, arguments: List[str]):
    # Copy the template and then replace the arguments placeholder with the values
    template = (Path(__file__).parent.absolute() / "scripts" / "vscode_attach.template.sh").read_text()
    arguments = join_str(arguments).strip()
    template = template.replace("[ARGUMENTS]", arguments)
    unique_timestamp = int(datetime.now().timestamp())
    tmp_file = Path(f"/tmp/singularity_vscode_attach_{unique_timestamp}.sh")
    tmp_file.write_text(template)
    path = copy_to_tools_folder(tmp_file, f"vscode_attach_{job_name}.sh")
    tmp_file.unlink()
    return path


def run_singularity_job(
    command: str, command_args: List[str], batch: bool, salloc: SallocArgs, singularity: SingularityArgs
):
    alloc_args, singularity_args = prepare_slurm_and_singularity_args(salloc, singularity)
    singularity_args += ["--bind", f"{scratch_path()}:{scratch_path()}"]
    script_command = [command] + command_args
    local_run_script_path = Path(__file__).parent.absolute() / "scripts" / "singularity_exec.sh"
    iris_run_script_path = copy_to_tools_folder(local_run_script_path, local_run_script_path.name)
    run_command = [
        str(iris_run_script_path),
        join_str(singularity_args),
        singularity.singularity_image,
        join_str(script_command),
    ]
    if batch:
        # Schedule job with sbatch
        batch_args = ["-N", 1, "--output=%x-%j.out"]
        exec(["sbatch"] + batch_args + alloc_args + run_command, exec_on_iris=True)
    else:
        exec(["srun"] + alloc_args + run_command, exec_on_iris=True)


def setup_for_vscode_attach(salloc: SallocArgs, singularity: SingularityArgs):
    if on_iris():
        die("Error: the vscode attach script should be run on your local machine, not on the iris cluster")
    # Check that singularity image exists on iris, otherwise attach will fail later on
    try:
        exec(["ls", singularity.singularity_image], exec_on_iris=True, check=True, echo_command=True)
    except:
        die(f"Error: File {singularity.singularity_image} not found on iris cluster. If the path looks right, check that you can connect to iris by running `ssh iris-cluster`.")

    # Check that SSH is probably configured on local machine
    ssh_config = sshconf.read_ssh_config(Path.home() / ".ssh" / "config")
    ssh_identity_file = ssh_config.host("iris-cluster").get("identityfile")
    if ssh_identity_file is None:
        die(
            f"Could not read IdentityFile in your ssh config. Check the README for instructions on how to setup your iris-cluster host in SSH config."
        )
    L.info(f"Will use SSH identity {ssh_identity_file}")

    alloc_args, singularity_args = prepare_slurm_and_singularity_args(salloc, singularity)
    scratch = scratch_path()
    singularity_args += ["--bind", f"{scratch}:{scratch}"]
    vscode_attach_script_path = copy_vscode_attach_script_to_tools(salloc.job_name, singularity_args + [singularity.singularity_image])

    # TODO use srun inside the vscode-attach script directly, alloc is not needed!
    # TODO Adjust SSH config automagically
    exec(["salloc", "--no-shell"] + alloc_args, exec_on_iris=True)

    # Find allocated nodeget_allocated_node_by_jobname
    allocated_node = get_allocated_node_by_jobname(salloc.job_name)
    L.info(f"Successful allocation on {allocated_node}")

    # Update local SSH settings for easy vscode attach
    ssh_host = f"{salloc.job_name}-vscode"
    iris_username = exec_output_sync(["whoami"], exec_on_iris=True)
    remote_command = f'bash {vscode_attach_script_path}'
    L.info(f"Updating your SSH settings to allow VSCode to attach to target `{ssh_host}`")
    values = {
        "HostName": allocated_node,
        "ProxyJump": "iris-cluster",
        "User": iris_username,
        "IdentityFile": ssh_identity_file,
        "RemoteCommand": remote_command,
    }
    if ssh_host in ssh_config.hosts():
        ssh_config.set(ssh_host, **values)
    else:
        ssh_config.add(ssh_host, **values)
    ssh_config.save()
    L.info("All done!")
    L.info(f"Attach VSCode to SSH Remote '{ssh_host}'.")
    L.info(
        f"Don't forget to scancel your job if you're done before it expires: `ssh iris-cluster scancel --name {salloc.job_name}`"
    )


def convert_docker_to_sif(tag: str, source: str, sif_path: Path):
    tag_nospace =  tag.replace("/", "-").replace(":", "-").replace(" ", "-")
    def alloc_convert_node():
        L.info(f"Allocating node to convert image to SIF file")
        job_name = f"docker-conversion-{tag_nospace}"
        exec(["salloc", "--no-shell", "-J", job_name, "-p", "interactive", "--qos", "debug", "--mem", "12G", "-c", "4", "-t", "01:00:00"], exec_on_iris=True)
        return get_allocated_node_by_jobname(job_name), job_name
    assert source in ["local", "registry"], f"Invalid source '{source}'"
    if source == "local":
        # If local: export local image to tar file, upload to HPC, and convert to singularity
        tar_image_path: Path = Path("/tmp") / f"{tag_nospace}.tar"
        L.info(f"Exporting {tag} to {tar_image_path} on your local machine")
        if tar_image_path.exists():
            L.info(f"{tar_image_path} already exists, reusing it. If you wish to export the image again, delete this file.")
        else:
            exec(["docker", "save", "-o", str(tar_image_path), tag], exec_on_iris=False)
        L.info(f"Uploading {tar_image_path} to HPC path {remote_tar_image_path}")
        remote_tar_image_path = sif_path.parent / tar_image_path.name
        exec(["scp", str(tar_image_path), f"iris-cluster:{remote_tar_image_path}"], exec_on_iris=False, echo_command=False)
        allocated_node, jobname = alloc_convert_node()
        L.info(f"Converting {tar_image_path} to SIF file at {sif_path}")
        exec(["ssh", "-J", "iris-cluster", "-o", "StrictHostKeyChecking=no", allocated_node, "bash", "-l", "-c", f'"module load tools/Singularity && singularity build {sif_path} docker-archive://{remote_tar_image_path}"'], exec_on_iris=False)
        L.info(f"Removing tmp files {tar_image_path} and iris-cluster:{tar_image_path}")
        exec(["rm", tar_image_path], exec_on_iris=False, echo_command=False)
        exec(["rm", remote_tar_image_path], exec_on_iris=True, echo_command=False)
    else:
        allocated_node, jobname = alloc_convert_node()
        L.info(f"Converting {tag} to SIF file at {sif_path}")
        exec(["ssh", "-J", "iris-cluster", "-o", "StrictHostKeyChecking=no", allocated_node, "bash", "-l", "-c", f'"module load tools/Singularity && singularity build {sif_path} docker://{tag}"'], exec_on_iris=False)
    L.info(f"Releasing allocated resources")
    exec(["scancel", f"--name={jobname}"], check=False, exec_on_iris=True, echo_command=False)
    L.info(f"All done!")


if __name__ == "__main__":
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="subparser")
    
    # docker-convert subcommand: used to create a SIF image from a local docker tag, or from a tag from an online registry
    docker_convert_subparser = subparsers.add_parser(
        "docker-convert",
        help="Converts a local Docker image, or an online image found on a public registry",
    )
    docker_convert_subparser.add_argument(f"--source", choices=["local", "registry"], default="local", help="Whether the given tag is local or hosted on a remote registry. Default is 'local'. If local, the image will be automatically saved and uploaded to HPC before conversion.")
    docker_convert_subparser.add_argument(f"--tag", type=str, help="The local Docker image tag or a tag to an image hosted on an online registry.", required=True)
    docker_convert_subparser.add_argument(f"--sif-path", type=Path, required=True, help="The path on HPC where the converted Singularity image (SIF file) will be stored.")
    

    # attach-vscode subcommand: used to prepare a local VSCode to attach to a container
    vscode_subparser = subparsers.add_parser(
        "attach-vscode",
        help="Allocates resources and sets up an iris node to let VSCode attach to it. Also automagically sets up your SSH config.",
    )
    SallocArgs.add_args_to_parser(vscode_subparser)
    SingularityArgs.add_args_to_parser(vscode_subparser)

    # run subcommand: used to run a singularity job on cluster
    run_subparser = subparsers.add_parser(
        "run", help="Runs a singularity job on the cluster, either synchronously with srun or queuing it with sbatch."
    )
    SallocArgs.add_args_to_parser(run_subparser)
    SingularityArgs.add_args_to_parser(run_subparser)
    run_subparser.add_argument(
        "--batch",
        action="store_true",
        help="If specified, the job is run using `sbatch`, which will queue it and run it once resources are available. By default, jobs are run using `srun`, which blocks until resources are available.",
    )
    run_subparser.add_argument(
        "command",
        type=str,
        help="Command to run inside the Singularity container. Arguments can be specified after the command, eg. '--batch_size 32'.",
    )
    run_subparser.add_argument("command_args", nargs=REMAINDER, type=str)

    args = parser.parse_args()
    if args.subparser == "docker-convert":
        convert_docker_to_sif(args.tag, args.source, args.sif_path)
    elif args.subparser in ["attach-vscode", "run"]:
        salloc = SallocArgs.from_args(args)
        salloc.job_name = salloc.job_name.replace(" ", "_")
        singularity = SingularityArgs.from_args(args)
        if args.subparser == "attach-vscode":
            setup_for_vscode_attach(salloc, singularity)
        elif args.subparser == "run":
            run_singularity_job(args.command, args.command_args, args.batch, salloc, singularity)
    else:
        raise Exception(f"Unsupported subparser: {args.subparser}")
