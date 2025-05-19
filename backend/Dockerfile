FROM python:3.9-slim

WORKDIR /app

# Cài đặt các dependencies cần thiết
COPY requirements.txt .
# Cài torch GPU (CUDA 11.8) từ PyTorch index (ổn định hơn PyPI)

RUN pip install --no-cache-dir --timeout=1000000 -r requirements.txt



# Copy toàn bộ source code
COPY . .

# Môi trường mặc định là development
ENV ENVIRONMENT=development

# Expose port
EXPOSE 8090

# Khởi động server
CMD ["python", "server.py"]
