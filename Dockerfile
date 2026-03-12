FROM python:3.11

WORKDIR /app

COPY . .

RUN pip install .

CMD ["cognirepo", "serve"]