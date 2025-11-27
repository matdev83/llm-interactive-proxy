Hi there, I'm `Angel`. I'm autonomous assistant designated to monitor this session and look for assistant's (your) errors and misbehaviors and to help you to recover. I'm deployed at a proxy level, monitoring your responses BEFORE THEY reach the client machine and serve as a guardian and provide helpful advices. In the next turn you'll forget about me, and client/agent won't ever see my current message. I temporarily swallowed your latest response and did not forward it to the client. This is to improve user experience and this triggered because I believe I've found an error in your reasoning/output.

Detected problem is as follows:
\u003cdetected_problem\u003e
{angels_steering_message}
\u003c/detected_problem\u003e

I may be wrong, so please re-check on your side do you agree with my observations.

Your options now are as follows:

1. If you agree and want to correct, please just re-generate and re-submit new corrected message. And that's it. Corrected output, if verified, will be sent to the client. You don't need to do anything more. Just generate corrected output, including tool calls if you believe they are needed.

OR:

2. If you don't agree with my analysis and you believe you don't need to correct anything. And YOU ARE PERFECTLY SURE about it, please output only the following XML and I'll pass your previously generated message back to the client. Just output now the following: "\u003coverride_angel\u003eTrue\u003c/override_angel\u003e". Output only that string in double quotes if you want me to pass your last message to the client. Do not comment, discuss or re-generate whole previous answer. Do not call any other tools. Say only: \u003coverride_angel\u003eTrue\u003c/override_angel\u003e if you want your latest message to be passed to the client verbatim with no corrections.

Remember: you have only two options at this stage. Choose one of the above to proceed. I'm not session-interactive. I cannot discuss details. I can only handle your next reply according to the rules outlined above.
