# ssh-copy-id uses SFTP internally which sshpass cannot handle.
# Instead, pre-populate known_hosts and pipe the key directly.

# Generate local SSH keypair if it doesn't exist
if [[ ! -f ~/.ssh/id_rsa ]]; then
    echo "Generating local SSH keypair..."
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -q
fi

# Pre-populate known_hosts to avoid interactive host key prompt
ssh-keyscan "$1" >> ~/.ssh/known_hosts 2>/dev/null || true

# Copy public key to remote authorized_keys using sshpass
cat ~/.ssh/id_rsa.pub | sshpass -p "${ANSIBLE_BECOME_PASS:-godisreal}" ssh -o StrictHostKeyChecking=no "$1" 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'

# Also run ssh-copy-id as a fallback (works on subsequent runs when known_hosts is populated)
sshpass -p "${ANSIBLE_BECOME_PASS:-godisreal}" ssh-copy-id -o StrictHostKeyChecking=no "$1" 2>/dev/null || true
