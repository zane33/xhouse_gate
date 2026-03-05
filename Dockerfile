FROM python:3.11-slim
WORKDIR /app
RUN pip install flask requests
COPY server.py .
ENV XHOUSE_EMAIL=""
ENV XHOUSE_PASSWORD=""
ENV PORT=8765
EXPOSE 8765
CMD ["python", "server.py"]