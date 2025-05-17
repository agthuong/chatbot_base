FROM node:18-alpine as build

WORKDIR /app

# Copy package.json và package-lock.json
COPY package*.json ./

# Cài đặt dependencies
RUN npm ci

# Copy toàn bộ source code
COPY . .

# Build ứng dụng
RUN npm run build

# Stage 2: Sử dụng nginx để phục vụ static files
FROM nginx:alpine

# Copy build artifacts từ stage trước vào thư mục mặc định của nginx
COPY --from=build /app/dist /usr/share/nginx/html

# Copy cấu hình nginx tùy chỉnh (nếu cần)
# COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Khởi động nginx với foreground để container không tự tắt
CMD ["nginx", "-g", "daemon off;"] 