def compress_messages(messages):

    system_messages = []

    normal_messages = []

    for message in messages:

        if message["role"] == "system":

            system_messages.append(
                message
            )

        else:

            normal_messages.append(
                message
            )

    normal_messages = normal_messages[-6:]

    return (

        system_messages +

        normal_messages

    )