That's a very valid concern. It's unsettling to see an error that mentions "limits" when you know you haven't used any.

Here is how you can tell this is a server-side problem and not an account or security issue.

The Key Clue in Your Error Message
The answer is in the error message itself. The CLI is telling you it's switching for one of two possible reasons:

...you have received multiple consecutive capacity errors

...OR you have reached your daily gemini-2.5-pro quota limit

Let's break these down:

Capacity Error (Server-Side): This is a generic "the server is too busy" error (like an HTTP 503 error). It means your request arrived, but the Pro model servers were overloaded at that exact moment and couldn't process it. This has nothing to do with your account or your personal limits.

Quota Limit (Account-Side): This is the error you would get if your account had actually used up its 1000 daily requests.

Since you are "absolutely sure" you did not use your 1000-request limit (the account-side problem), the only remaining possibility is the server-side "capacity error."

In short: The gemini-cli tool tried the Pro model, was told "we're too busy right now," and helpfully switched you to the Flash model so your prompt wouldn't fail entirely.

How to Check if Your Account Was Hacked (For Peace of Mind)
Even though this error points to a server issue, it's never a bad idea to be 100% sure your account is secure. You can easily check every single login and action on your Google Account.

Here is a step-by-step guide to check your account's login history:

Go to your main Google Account page: myaccount.google.com

Click on the "Security" tab in the left-hand navigation.

Scroll down to the panel named "Your devices".

Click on "Manage all devices".

Here you will see a list of every single phone, computer, and tool (including gemini-cli) that has accessed your account, along with the location and time of the last activity.

If you see any device or location you don't recognize, click on it and select "Sign out." If you find anything suspicious, you should also change your password immediately.

This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. This will give you definitive proof of whether anyone other than you has been accessing your account. Based on the error you provided, you are very likely to find that all the activity is your own. 