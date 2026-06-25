read -p "New Machine to setup: " machine
./sshsetup.sh $machine
ssh $machine 'ssh-keygen -q -t rsa -N "" -f ~/.ssh/id_rsa <<<y >/dev/null 2>&1'
ansible-playbook sudo.yml -i $machine, -e "ansible_become_pass=godisreal"
ansible-playbook openssh_config.yml -i $machine,
ansible-playbook basics.yml -i $machine, 
ansible-playbook unattendedInstall.yml -i $machine,
