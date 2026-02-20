#!/bin/bash
echo "Enter your Hugging Face username (e.g. mohi679):"
read username

echo "Enter your Hugging Face ACCESS TOKEN (starts with hf_...):"
read token

echo "Ensure you have created a Space named 'clinical-graphrag-backend' with Docker."
echo "We will now push the backend directory to that space."

# Embed the credentials into the URL so it bypasses prompts entirely
git clone https://$username:$token@huggingface.co/spaces/$username/clinical-graphrag-backend /tmp/hf_space

if [ $? -ne 0 ]; then
    echo "ERROR: Authentication failed or the Space does not exist!"
    echo "Make sure the token has WRITE access and the Space is completely empty (no README)."
    exit 1
fi

cp backend/requirements.txt /tmp/hf_space/
cp backend/Dockerfile.hf /tmp/hf_space/Dockerfile
cp -r backend/app /tmp/hf_space/
cd /tmp/hf_space

git add .
git commit -m "Deploy backend"
git push -u origin main

if [ $? -eq 0 ]; then
    echo "Successfully pushed to Hugging Face!"
else
    echo "ERROR: Failed to push to Hugging Face."
fi
