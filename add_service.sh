#!/bin/bash -ex

sudo ln -s $(pwd)/$1 /etc/systemd/system
sudo systemctl daemon-reload
