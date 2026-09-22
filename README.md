# Web Application

## Build and run

Make sure Docker Desktop is running, then open a terminal in this project folder.

```cmd
docker build --tag hw1-web-app:1.0 .
docker run --name hw1-web --detach --publish 8080:8080 hw1-web-app:1.0
```

Open http://localhost:8080 in a browser.

To stop and remove the container:

```cmd
docker stop hw1-web
docker rm hw1-web
```
