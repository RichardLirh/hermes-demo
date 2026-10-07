FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
USER root
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 DISPLAY=:99
RUN apt-get update && apt-get install -y --no-install-recommends x11vnc novnc websockify fonts-noto-cjk tini \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir playwright==1.63.0
WORKDIR /opt/browser-runtime
COPY . /opt/browser-runtime/
RUN mkdir -p /home/pwuser/artifacts && chown -R pwuser:pwuser /home/pwuser /opt/browser-runtime
USER pwuser
ENV HOME=/home/pwuser
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "runtime.py"]
