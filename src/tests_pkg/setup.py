from setuptools import find_packages, setup

setup(
    name='tests_pkg',
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/tests_pkg']),
        ('share/tests_pkg', ['package.xml']),
    ],
    entry_points={'console_scripts': [
        'approach_test_node = tests_pkg.nodes.approach_test_node:main',
    ]},
)
