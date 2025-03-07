import frappe
from frappe.model.document import Document
from frappe.utils import get_url_to_form

import frappe.utils
from frappe_slack_connector.db.leave_application import custom_fields_exist
from frappe_slack_connector.helpers.error import generate_error_log
from frappe_slack_connector.helpers.standard_date import standard_date_fmt
from frappe_slack_connector.slack.app import SlackIntegration


def send_leave_notification(doc):
    """
    Send a slack message to the leave approver when a new leave application
    is submitted
    """
    frappe.enqueue(
        send_leave_notification_bg,
        queue="short",
        doc=doc,
    )

def send_final_notification(doc):
    #  frappe.enqueue(
    #     send_final_notification_bg,
    #     queue="short",
    #     doc=doc,
    # )
    send_final_notification_bg(doc)
    
def send_final_notification_bg(doc:Document):
    slack = SlackIntegration()

    try:
        user_slack = slack.get_slack_user_id(employee_id=doc.employee)

    except Exception as e:
        generate_error_log(
            title="Error fetching approver slack id",
            exception=e,
        )
        user_slack = None
    blocks=[]
    if doc.workflow_state=="Approved":
        blocks=format_leave_approve_block(
                        leave_id=str(doc.name),
                        leave_type=doc.leave_type,
                        from_date=standard_date_fmt(doc.from_date),
                        to_date=standard_date_fmt(doc.to_date),
                        approve_date=standard_date_fmt(frappe.utils.now())
                    )
    if doc.workflow_state=="Rejected":
        blocks=format_leave_reject_block(
                            leave_id=str(doc.name),
                            leave_type=doc.leave_type,
                            from_date=standard_date_fmt(doc.from_date),
                            to_date=standard_date_fmt(doc.to_date),
                            reject_date=standard_date_fmt(frappe.utils.now())
                        )
    print("doc.workflow_state",doc.workflow_state)
    if doc.workflow_state=="Cancelled":
        blocks=format_leave_cancel_block(
                            leave_id=str(doc.name),
                            leave_type=doc.leave_type,
                            from_date=standard_date_fmt(doc.from_date),
                            to_date=standard_date_fmt(doc.to_date),
                            cancel_date=standard_date_fmt(frappe.utils.now())
                        )
    # send message to requester
    if user_slack is not None and blocks is not None:
        slack.slack_app.client.chat_postMessage(
                channel=user_slack,
                blocks=blocks
            )

def send_leave_notification_bg(doc: Document):
    """
    Send a slack message to the leave approver when
    a new leave application is submitted

    Also send a notification to the attendance channel thread if
    the leave date is today and attendance notification is already sent
    """
    slack = SlackIntegration()
    try:
        approver_slack = slack.get_slack_user_id(user_email=doc.leave_approver)
    except Exception as e:
        generate_error_log(
            title="Error fetching approver slack id",
            exception=e,
        )
        approver_slack = None

    try:
        user_slack = slack.get_slack_user_id(employee_id=doc.employee)
        mention = f"<@{user_slack}>" if user_slack else doc.employee_name
        day_period = "Full Day"
        if doc.half_day and doc.half_day_date == frappe.utils.today():
            day_period = doc.custom_first_halfsecond_half if custom_fields_exist() else "Half Day"

        # if leave date is today and attendance notification is already sent,
        # send notification to attendance channel thread
        slack_settings = frappe.get_single("Slack Settings")
        # if (
        #     doc.from_date == frappe.utils.today()
        #     and slack_settings.send_attendance_updates == 1
        #     and slack_settings.last_attendance_date is not None
        #     and slack_settings.last_attendance_msg_ts is not None
        #     and slack_settings.last_attendance_date == frappe.utils.nowdate()
        # ):
        #     slack.slack_app.client.chat_postMessage(
        #         channel=slack.SLACK_CHANNEL_ID,
        #         blocks=[
        #             {
        #                 "type": "section",
        #                 "text": {
        #                     "type": "mrkdwn",
        #                     "text": f"{mention} requested for leave today. " + f"_({day_period})_",
        #                 },
        #             },
        #         ],
        #         thread_ts=slack_settings.last_attendance_msg_ts,
        #         reply_broadcast=True,
        #     )

        # Send message to approver
        if approver_slack is not None:
            slack.slack_app.client.chat_postMessage(
                channel=approver_slack,
                blocks=format_leave_application_blocks_for_approver(
                    leave_id=doc.name,
                    leave_link=get_url_to_form("Leave Application", doc.name),
                    employee_name=mention,
                    leave_type=doc.leave_type,
                    is_half_day=doc.half_day,
                    leave_submission_date=standard_date_fmt(doc.creation),
                    from_date=standard_date_fmt(doc.from_date),
                    to_date=standard_date_fmt(doc.to_date),
                    reason=doc.description,
                ),
            )

        # send message to requester
        if user_slack is not None:
            slack.slack_app.client.chat_postMessage(
                    channel=user_slack,
                    blocks=format_leave_application_blocks_for_requester(
                        leave_id=doc.name,
                        leave_link=get_url_to_form("Leave Application", doc.name),
                        employee_name=mention,
                        leave_type=doc.leave_type,
                        is_half_day=doc.half_day,
                        leave_submission_date=standard_date_fmt(doc.creation),
                        from_date=standard_date_fmt(doc.from_date),
                        to_date=standard_date_fmt(doc.to_date),
                        reason=doc.description,
                    ),
                )
            

    except Exception as e:
        generate_error_log(
            title="Error posting message to Slack",
            exception=e,
        )

def format_leave_application_blocks_for_approver(
    *,
    leave_id: str,
    employee_name: str,
    leave_type: str,
    leave_submission_date: str,
    from_date: str,
    to_date: str,
    is_half_day: bool,
    reason: str = "",
    employee_link: str = "#",
    leave_link: str = "#",
) -> list:
    """
    Format the blocks for the leave application message
    """
    blocks = [
        # {
        #     "type": "header",
        #     "text": {
        #         "type": "plain_text",
        #         "text": ":memo: New Leave Application",
        #         "emoji": True,
        #     },
        # },
       {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text":  f"""{employee_name} has submitted a new leave request.(<{leave_link}|{leave_id}>)\n*Leave Type:* {leave_type} \n*Submitted On:* {leave_submission_date}\n*From:* {from_date} \n*To:* {to_date}"""
        },
    },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Reason:*\n>{reason if reason else 'No reason provided'}",
            },
        },
    ]

    # Add a context menu indicating it is a half day
    if is_half_day:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Half Day: :white_check_mark:",
                    }
                ],
            }
        )

    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "actions",
                "block_id": "leave_actions_block",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "emoji": True, "text": "Approve"},
                        "style": "primary",
                        "value": leave_id,
                        "action_id": "leave_approve",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "emoji": True, "text": "Reject"},
                        "style": "danger",
                        "value": leave_id,
                        "action_id": "leave_reject",
                    },
                ],
            },
            {
                "type": "context",
                "block_id": "footer_block",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Please review and take action on this leave request.",
                    }
                ],
            },
        ]
    )
    return blocks

def format_leave_application_blocks_for_requester(
    *,
    leave_id: str,
    employee_name: str,
    leave_type: str,
    leave_submission_date: str,
    from_date: str,
    to_date: str,
    is_half_day: bool,
    reason: str = "",
    employee_link: str = "#",
    leave_link: str = "#",
) -> list:

    blocks = [
        # {
        #     "type": "header",
        #     "text": {
        #         "type": "plain_text",
        #         "text": ":memo: New Leave Application",
        #         "emoji": True,
        #     },
        # },
       {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text":  f"""Your leave request has been submitted successfully!(<{leave_link}|{leave_id}>).\n*Leave Type:* {leave_type} \n*Submitted On:* {leave_submission_date}\n*From:* {from_date} \n*To:* {to_date}"""
        },
    },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Reason:*\n>{reason if reason else 'No reason provided'}",
            },
        },
    ]

    # Add a context block if it's a half-day leave
    if is_half_day:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Half Day: :white_check_mark:",
                    }
                ],
            }
        )

    blocks.append(
        {
            "type": "context",
            "block_id": "footer_block",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "You will receive a notification once your request is reviewed.",
                }
            ],
        }
    )
    return blocks

def format_leave_approve_block( *,
    leave_id: str,
    leave_type: str,
    from_date: str,
    to_date: str,
    approve_date:str,
    leave_link: str = "#",
) -> list:
    blocks = [
                # {
                #     "type": "header",
                #     "text": {
                #         "type": "plain_text",
                #         "text": ":white_check_mark: Leave Application Approved",
                #         "emoji": True,
                #     },
                # },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
            "text":  f"""Your leave request has been *Approved* (<{leave_link}|{leave_id}>).\n*Leave Type:* {leave_type} \n*Approved On:* {approve_date}\n*From:* {from_date} \n*To:* {to_date}"""

                    },
                }
              
            ]

    return blocks

def format_leave_reject_block(
    leave_id: str,
    leave_type: str,
    from_date: str,
    to_date: str,
    reject_date:str,
    leave_link: str = "#",
)-> list:
    blocks = [
        # {
        #     "type": "header",
        #     "text": {
        #         "type": "plain_text",
        #         "text": ":x: Leave Application Rejected",
        #         "emoji": True,
        #     },
        # },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
             
            "text":  f"""Your leave request has been *Rejected* .(<{leave_link}|{leave_id}>).\n*Leave Type:* {leave_type} \n*Rejected On:* {reject_date}\n*From:* {from_date} \n*To:* {to_date}"""

            },
        },
       
    ]
    return blocks

def format_leave_cancel_block(
    leave_id: str,
    leave_type: str,
    from_date: str,
    to_date: str,
    cancel_date:str,
    leave_link: str = "#",
)-> list:
    blocks = [
        # {
        #     "type": "header",
        #     "text": {
        #         "type": "plain_text",
        #         "text": ":warning: Leave Application Cancelled",
        #         "emoji": True,
        #     },
        # },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "",
            "text":  f"""Your leave request has been *Cancelled* .(<{leave_link}|{leave_id}>).\n*Leave Type:* {leave_type} \n*Cancelled On:* {cancel_date}\n*From:* {from_date} \n*To:* {to_date}"""

            },
        },
      
     
    ]
    return blocks


