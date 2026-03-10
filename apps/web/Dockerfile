FROM node:20-alpine

WORKDIR /app

ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

RUN npm run build

# Create non-root user
RUN addgroup -g 1001 -S opentutor && adduser -S opentutor -u 1001 -G opentutor \
    && chown -R opentutor:opentutor /app

USER opentutor

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:3001 || exit 1

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3001"]
