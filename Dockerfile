FROM ubuntu

RUN apt update -y
RUN apt -y install sudo git vim cron tree
RUN apt -y install python3 python3-pip
RUN apt -y install gettext

ENV USER=ubuntu
RUN echo "$USER ALL=(ALL:ALL) NOPASSWD: ALL" > /etc/sudoers.d/$USER

USER $USER
WORKDIR /home/${USER}

ARG HOST_IP
ENV HOST_IP=${HOST_IP}

COPY assets/install.sh install.sh
COPY assets/entrypoint.sh entrypoint.sh
COPY assets/run_server.sh run_server.sh

COPY assets/tmp tmp
COPY assets/pinctrl_dummy.py pinctrl_dummy.py

COPY assets/devices devices
COPY assets/db_fixtures db_fixtures

COPY _tmp/* tmp/

RUN ./install.sh

RUN sudo rm -rf tmp

ENV TERM=xterm-256color
EXPOSE 8000

CMD ["./entrypoint.sh"]
