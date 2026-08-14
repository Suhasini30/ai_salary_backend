import asyncio
from app.ai.voice import speech_to_text, text_to_speech

async def main():

    audio_file = "recording\query.ogg"   

    transcript, response = await speech_to_text(audio_file)

    print(f"Transcript: {transcript}")
    print(f"Response: {response}")

    output = await text_to_speech(response)

    print(output)

asyncio.run(main())