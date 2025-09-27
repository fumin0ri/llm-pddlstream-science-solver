# Building NL2Plan Without Docker
The following are instructions on how to use NL2Plan without Docker. However, we generally recommend that you use Docker as it's simpler. For instructions on how to use Docker, see [the main README](./README.md).

These instructions assume that you're using Linux or WSL. They've been tested on Ubuntu 22.04 and might require adaptations for other Linux versions.

## Python Environment
The repo has primarily been tested for Python 3.11.

You can set up a Python environment using either [Conda](https://conda.io) or [venv](https://docs.python.org/3/library/venv.html) and install the dependencies via the following steps.

**Conda**
```
conda create -n NL2Plan python=3.11
conda activate NL2Plan
pip install -r requirements.txt
```

**venv**
```
python3.11 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

These environments can then be exited with `conda deactivate` and `deactivate` respectively. The instructions below assume that a suitable environment is active.

## Api Key
NL2Plan requires access to an LLM. The easiest option is to use OpenAI's GPT models. For this, specify your API key in the `OPENAI_API_KEY` environmental variable.
```
export OPENAI_API_KEY='YOUR-KEY' # e.g. OPENAI_API_KEY='sk-123456'
```
Note that this must be done in each terminal you intend to use NL2Plan in.

## Fast Downward
NL2Plan uses the [Fast Downward](https://github.com/aibasel/downward) planning system. To set it up, run the following from the root of this repo.

```
# Install dependencies
sudo apt install cmake g++ git make python3
# Pull the repo
git clone https://github.com/aibasel/downward.git
# Build Fast Downward
./downward/build.py
```

## Validators
NL2Plan uses three validators. All of these must be placed within [this directory](./). If you run the following commands from the root of this directory, they will be correctly placed.

### cpddl
Running [cpddl](https://gitlab.com/danfis/cpddl) requires Apptainer. Install it if not already installed:
```
apt update
apt install -y libfuse3-3 uidmap squashfs-tools fakeroot wget
wget https://github.com/apptainer/apptainer/releases/download/v1.3.4/apptainer_1.3.4_amd64.deb
apt install -y ./apptainer_1.3.4_amd64.deb
rm apptainer_1.3.4_amd64.deb
apptainer --version
```

Next, download the cpddl Apptainer:
```
apptainer pull oras://registry.gitlab.com/danfis/cpddl:latest
```

### Loki
You can download and install [Loki](https://github.com/drexlerd/Loki/tree/main) via the following:
```
git clone https://github.com/drexlerd/Loki.git
cd Loki
git checkout c79b38f
cmake -S dependencies -B dependencies/build -DCMAKE_INSTALL_PREFIX=dependencies/installs
cmake --build dependencies/build -j16
cmake -S . -B build -DCMAKE_PREFIX_PATH=${PWD}/dependencies/installs
cmake --build build -j16
cd ..
```

### VAL
You can download and install [VAL](https://github.com/KCL-Planning/VAL/tree/master) via the following:
```
git clone https://github.com/KCL-Planning/VAL.git
./VAL/scripts/linux/build_linux64.sh all release
```