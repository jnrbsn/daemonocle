from setuptools import setup

with open('README.rst', 'r') as f:
    long_description = f.read().split('\n\n-----\n\n', 1)[1].lstrip()

with open('HISTORY.rst', 'r') as f:
    long_description += '\n' + f.read()

setup(
    name='daemonocle',
    version='1.1.0',
    description='A Python library for creating super fancy Unix daemons',
    long_description=long_description,
    url='http://github.com/jnrbsn/daemonocle',
    author='Jonathan Robson',
    author_email='jnrbsn@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Operating System :: MacOS',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX',
        'Operating System :: POSIX :: BSD',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Unix',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
    keywords='daemon daemonize fork linux macos bsd unix posix cli',
    packages=['daemonocle'],
    install_requires=[
        'click',
        'futures; python_version=="2.7"',
        'psutil',
    ],
    extras_require={
        'test': [
            'coveralls',
            'flake8',
            'flake8-isort; python_version>="3.6"',
            'pytest',
            'pytest-cov',
        ],
    },
)
