FROM public.ecr.aws/lambda/python:3.13

COPY handler.py ${LAMBDA_TASK_ROOT}/

RUN python -m pip install --no-cache-dir pillow==10.4.0 boto3==1.34.144

CMD ["handler.handler"]