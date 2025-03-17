# mfethuls

## 🚀 About

A package housing an array of python based tools or utilities for the lab.<br> 
The focus is on creating a library of analytical instrumentation and 
writing utilities for each.

## 🔧 Install
It is recommended to build from within a virtual environment:<br> 
https://docs.python.org/3/library/venv.html

The package is pip installable (ssh recommended):
```shell
# ssh
pip install git+ssh://git@github.com/lucaAyt/mfethuls.git
```
To setup ssh keys see the following:<br>
https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent

For development installation, the following is recommended:
```shell
# For development purposes it is best to clone and then pip install as an editable.
git clone ssh://git@github.com/lucaAyt/mfethuls.git
cd mfethuls
pip install -e .
```

## 🚁 Usage


For usage you will need to edit the **.env_example** file after installation.<br>Consult the notebook ``notebooks\tutorial_basic_usecase`` for an example.
For developers, please work on a suitable branch and send a pull request.

## 📃 License

MIT

