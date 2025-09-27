FROM ubuntu:latest

# Install prerequisites for adding new repositories
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update

# Install Python 3.11 and dev tools
RUN apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3-pip \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

# Make python3 and python point to python3.11
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    update-alternatives --set python3 /usr/bin/python3.11 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --set python /usr/bin/python3.11

# Install Git
RUN apt-get update && apt-get install -y git

# Set the working directory
WORKDIR /ws

# Install apptainer dependencies
RUN apt-get update && \
    apt-get install -y libfuse3-3 uidmap squashfs-tools fakeroot wget
    RUN wget https://github.com/apptainer/apptainer/releases/download/v1.3.4/apptainer_1.3.4_amd64.deb
    RUN apt install -y ./apptainer_1.3.4_amd64.deb
    RUN rm apptainer_1.3.4_amd64.deb
    RUN apptainer --version

# Install Fast Downward
    RUN apt install -y cmake g++ make
    RUN git clone https://github.com/aibasel/downward.git
    RUN cd downward && \
        git checkout 6e708b8 && \
        ./build.py
    # Uncomment the following lines to test your Fast Downward installation
    #RUN cd downward && \
    #    ./fast-downward.py misc/tests/benchmarks/miconic/s1-0.pddl --search "astar(lmcut())"

# Install CPDDL
    RUN apptainer pull oras://registry.gitlab.com/danfis/cpddl:v1.4
    RUN ls
    RUN mv cpddl_v1.4.sif cpddl_latest.sif
    # If you want to use the latest version of CPDDL, comment the previous line and uncomment the following line
    # RUN apptainer pull oras://registry.gitlab.com/danfis/cpddl:latest

# Install Loki
    RUN git clone https://github.com/drexlerd/Loki.git
    RUN cd Loki && \
        git checkout c79b38f && \
        cmake -S dependencies -B dependencies/build -DCMAKE_INSTALL_PREFIX=dependencies/installs && \
        cmake --build dependencies/build -j16 && \
        cmake -S . -B build -DCMAKE_PREFIX_PATH=${PWD}/dependencies/installs && \
        cmake --build build -j16

# Install VAL
    RUN git clone https://github.com/KCL-Planning/VAL.git
    RUN cd VAL && \
        git checkout 3c7a1f3 && \
        ./scripts/linux/build_linux64.sh all release

# Install Python dependencies
    COPY ./requirements.txt /ws/requirements.txt
    RUN pip install -r requirements.txt

# Set the entrypoint to run the Python application
ENTRYPOINT ["python", "main.py"]