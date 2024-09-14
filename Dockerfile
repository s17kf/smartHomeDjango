FROM ubuntu

RUN apt update -y
RUN apt -y install sudo git vim cron
RUN apt -y install python3 python3-pip


ENV USER=ubuntu
RUN echo "$USER ALL=(ALL:ALL) NOPASSWD: ALL" > /etc/sudoers.d/$USER

USER $USER
WORKDIR /home/$USER

ARG HOST_IP
ENV HOST_IP=${HOST_IP}

#todo: maybe all this copy commands could be replaced with a single "COPY assets/* ."
COPY assets/install.sh install.sh
COPY assets/entrypoint.sh entrypoint.sh
COPY assets/run_server.sh run_server.sh

COPY assets/tmp tmp

COPY assets/pinctrl_dummy.py pinctrl_dummy.py
COPY assets/devices devices

#todo: replace this with populating db based on some data file
COPY db.sqlite3 tmp/db.sqlite3

RUN ./install.sh

RUN sudo rm -rf tmp

ENV TERM=xterm-256color
EXPOSE 8000

CMD ["./entrypoint.sh"]
