FROM python:3.5-alpine

WORKDIR /build

RUN apk --no-cache add --virtual build-dependencies build-base git

COPY requirements/prod.txt requirements/

RUN apk --no-cache add libxml2-dev libxslt-dev \
    && pip install -r requirements/prod.txt

COPY source-for-build .

RUN DISTUTILS_DEBUG=true python setup.py install

RUN apk del build-dependencies

RUN rm -Rf source-for-build

WORKDIR /

COPY config.yaml .

CMD ["roiorbison", "-c", "config.yaml"]

