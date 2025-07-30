import openai

# Make sure the OPENAI_API_KEY is set in your environment variables
# to the same value as LLM_INTERACTIVE_PROXY_API_KEY
client = openai.OpenAI(base_url="http://127.0.0.1:8000/v1")

# First, set the project directory.
# The gemini-cli-batch backend requires a project directory to be set.
# We will use the current working directory.
client.chat.completions.create(
    model="gemini-cli-batch:gemini-2.5-pro",
    messages=[
        {
            "role": "user",
            "content": "!/set(project-dir=.)"
        }
    ]
)

# Now, send a prompt to the model to list directory contents and read a file.
completion = client.chat.completions.create(
    model="gemini-cli-batch:gemini-2.5-pro",
    messages=[
        {
            "role": "user",
            "content": "List the contents of the current directory. Then, read the first file you find whose name starts with the letter 'A' and provide its contents."
        }
    ]
)

print(completion.choices[0].message.content)