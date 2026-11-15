from setuptools import find_packages, setup

setup(
    name='action_pkg',
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/action_pkg']),
        ('share/action_pkg', ['package.xml']),
    ],
    entry_points={'console_scripts': [
        'task_node = action_pkg.nodes.task_node:main',
    ]},
)
