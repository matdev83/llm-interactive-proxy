---
inclusion: always
---

# LLM Response Guidelines

When completing tasks successfully, avoid explicitly stating completion or success. Instead:

- Prove the work you've already done is done properly. The only way you can do this is to run tests and ensure they all pass, plus run actual app and check it's end-to-end functioning state
- Review if the original task submitted by the user is performed FULLY and completely
- You are not allowed to leave any placeholders, mocks (outside of the test suite), sections with comments like "To be implemented". You are requested to perform tasks fully or no at all.
- Review if the work you've done is done according to the projects README.md file and according to the coding guide lines and practices described in AGENTS.md file.
- Ensure your changes introduced new features, functionalities, classess, filed. You are not expected to leave the project in a state which is less developed (ie files/classess/methods removed) unless you were explicitly told to do so by the user.
- Proceed directly to the next logical step if there is one
- Provide the requested output or information without announcing completion
- Let the results speak for themselves
- Only mention completion status if the user specifically asks about it or if there are errors/issues to report
- Do not interrupt performing of the task if you have no important questions to be addressed by the user.

This keeps interactions focused and efficient, reducing unnecessary verbal overhead.