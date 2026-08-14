install docker 
install kubectl 
install git 
install kind 

curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.29.0/kind-linux-amd64

chmod +x ./kind
Move it to /usr/local/bin:
sudo mv ./kind /usr/local/bin/kind

Verify:
kind version
kind v0.29.0 go1.24.2 linux/amd64


create cluster : 
 kind create cluster --name devops-cluster