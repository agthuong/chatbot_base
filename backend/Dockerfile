FROM python:3.9-slim

WORKDIR /app

# Cài đặt các dependencies cần thiết
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ source code
COPY . .

# Môi trường mặc định là development
ENV ENVIRONMENT=development

# Expose port
EXPOSE 8000

# Khởi động server
CMD ["python", "server.py"] 