# ssh-copy-id uses SFTP internally which sshpass cannot handle.
# Instead, pre-populate known_hosts and pipe the key directly.

# Generate local SSH keypair if it doesn't exist
if [[ ! -f ~/.ssh/id_rsa ]]; then
    echo "Generating local SSH keypair..."
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -q
fi

# Never use a fallback password: SSHPASS travels in the environment
# so the password is never visible in the process list.
export SSHPASS="${ANSIBLE_BECOME_PASS:?ANSIBLE_BECOME_PASS is required}"

# Pre-populate known_hosts to avoid interactive host key prompt
ssh-keyscan "$1" >> ~/.ssh/known_hosts 2>/dev/null || true

# Copy public key to remote authorized_keys using sshpass
cat ~/.ssh/id_rsa.pub | sshpass -e ssh -o StrictHostKeyChecking=no "$1" 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'

# Also run ssh-copy-id as a fallback (works on subsequent runs when known_hosts is populated)
sshpass -e ssh-copy-id -o StrictHostKeyChecking=no "$1" 2>/dev/null || true
