from setuptools import setup, find_packages

setup(
    name="llm-interactive-proxy",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "pytest",
        "openai==1.84.0",
    ],
    # Add other metadata as needed
    author="Your Name",
    author_email="your.email@example.com",
    description="A short description of my project.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/llm-interactive-proxy",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.10",
)
