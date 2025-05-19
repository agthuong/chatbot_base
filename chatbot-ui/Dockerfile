FROM node:18-alpine as build

WORKDIR /app

# Copy package.json và package-lock.json
COPY package*.json ./

# Cài đặt dependencies và TypeScript toàn cục
RUN npm install
RUN npm install -g typescript

# Copy toàn bộ source code
COPY . .

# Cấp quyền thực thi cho thư mục node_modules/.bin
RUN chmod -R 755 ./node_modules/.bin

# Build ứng dụng
RUN npm run build

# Stage 2: Sử dụng nginx để phục vụ static files
FROM nginx:alpine

# Copy build artifacts từ stage trước vào thư mục mặc định của nginx
COPY --from=build /app/dist /usr/share/nginx/html

# Copy cấu hình nginx tùy chỉnh
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Khởi động nginx với foreground để container không tự tắt
CMD ["nginx", "-g", "daemon off;"] 