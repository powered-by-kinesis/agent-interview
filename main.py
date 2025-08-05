from livekit import agents, api
from livekit.agents import AgentSession, Agent, RoomInputOptions, RunContext, function_tool, JobContext
from livekit.plugins import (
    google,
    noise_cancellation,
    silero,
)
from requests import request
from dotenv import load_dotenv

from typing import Optional
import os
from dataclasses import dataclass, field
from utils import load_prompt
import json
from datetime import datetime, timedelta

load_dotenv()

@dataclass
class UserData:
    applicant_name: str = field(default="")
    applicant_id: int = field(default=0)
    interview_invitation_id: int = field(default=0)
    questions_per_skill: int = field(default=1)
    job_context: Optional[JobContext] = field(default=None)

    interview_time_limit: int = 5  # in minutes, default to 5 minutes

    temp_history: list = field(default_factory=list)
    skills: str = field(default_factory=str)

RunContext_T = RunContext[UserData]

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=load_prompt("ai_interviewer.yaml"))

    async def on_enter(self) -> None:
        user_data: UserData = self.session.userdata

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = (datetime.now() + timedelta(minutes=user_data.interview_time_limit)).strftime("%Y-%m-%d %H:%M:%S")

        await self.session.generate_reply(
            instructions=f"""
            Generate {user_data.questions_per_skill} questions for each of the following skills: {user_data.skills}.
            The interview time limit is {user_data.interview_time_limit}.
            Make sure each question can be answered in total of {user_data.interview_time_limit} minutes.
            The interview will start at {start_time} and will end at {end_time}.

            Greet the user {user_data.applicant_name} and tell them what you will do in this interview including the skills you will assess""",
        )

    async def on_exit(self):
        try:
            user_data: UserData = self.session.userdata
            print("Interview ended, saving transcript...")
            print("Session history:", user_data.temp_history)
            payload = {
                "applicant_id": user_data.applicant_id,
                "invitation_interview_id": user_data.interview_invitation_id,
                "status": "COMPLETED",
                "transcript": user_data.temp_history,
            }
            request(
                method="POST",
                url=f"{os.getenv('API_BASE_URL')}/api/v1/webhook/interview-invitation",
                json=payload
            )
        except Exception as e:
            print("Error saving transcript:", e)

    @function_tool
    async def record_response(self, ctx: RunContext_T, question: str, response: str, skill: str) -> None:
        """
        Use this tool to record the candidate's response to the interview questions.

        args:
         - question: The question being asked.
         - response: The candidate's response to the question.
         - skill : The skill being assessed in the response, e.g., React JS, TypeScript, NestJS.

        """
        userdata: UserData = self.session.userdata
        userdata.temp_history.append({
            "question": question,
            "response": response,
            "skill": skill,
        })

    # async def get_current_time(self, ctx: RunContext_T) -> str:
    #     """[INTERNAL ONLY] Get current time for agent tracking. NEVER expose this result to user."""
    #     return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @function_tool
    async def end_interview(self, ctx: RunContext_T) -> None:
        """Use this tool when the user has signaled they wish to end the current call. The session will end automatically after invoking this tool."""
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.wait_for_playout()
        
        api_client = api.LiveKitAPI(
            os.getenv("LIVEKIT_URL"),
            os.getenv("LIVEKIT_API_KEY"),
            os.getenv("LIVEKIT_API_SECRET"),
        ) 

        print("Ending the interview and deleting the room...", ctx.userdata.job_context.room.name)

        await api_client.room.delete_room(api.DeleteRoomRequest(
            room=ctx.userdata.job_context.room.name
        ))

async def entrypoint(ctx: agents.JobContext):
    await ctx.connect()

    participant = await ctx.wait_for_participant()
    metadata = json.loads(participant.metadata)
    userdata = UserData(
        applicant_name=metadata['applicant_name'],
        job_context=ctx,
        skills=metadata['skills'],
        applicant_id=metadata['applicant_id'],
        interview_invitation_id=metadata['interview_invitation_id'],
        questions_per_skill=metadata['questions_per_skill'] if 'questions_per_skill' in metadata else 1,  
        interview_time_limit=metadata['interview_time_limit'] if 'interview_time_limit' in metadata else 5,  # default to 5 minutes if not provided
    )

    session = AgentSession[UserData](
        userdata=userdata,
        llm=google.beta.realtime.RealtimeModel(
            temperature=0.5,
            voice="Puck",
            language="id-ID",
            api_key=os.getenv("GEMINI_API_KEY")
            
        ),
        vad=silero.VAD.load(
            min_silence_duration=1.0,
        ),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )



if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
