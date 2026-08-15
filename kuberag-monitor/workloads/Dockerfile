FROM python:3.11-slim

WORKDIR /app

RUN pip install requests

COPY generate_load.py .

CMD ["python", "generate_load.py"]
