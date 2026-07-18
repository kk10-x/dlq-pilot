FROM python:3.12-slim
RUN pip install --no-cache-dir aio-pika>=9.4
COPY chaos.py /chaos.py
CMD ["python", "/chaos.py"]
