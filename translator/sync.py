import datetime
import os
import ssl
from os.path import basename, dirname, join

from github import Github, UnknownObjectException
from github import InputGitTreeElement
import gitlab
from github.Auth import AppAuthToken
from opensearchpy import OpenSearch
from opensearchpy.connection import create_ssl_context
from opensearchpy import Document, Date, Keyword, Object

INDEX_NAME = "github-commit-sync"


class GitLabSyncCommitGitHub(Document):
    gitlab = Object()
    github = Object()
    created = Date()

    class Index:
        name = INDEX_NAME

    def save(self, ** kwargs):
        return super(GitLabSyncCommitGitHub, self).save(** kwargs)


class GitLabToGitHubSync:
    GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN")
    GITLAB_URL = os.environ.get("GITLAB_URL")
    gitlab_client = gitlab.Gitlab(url=GITLAB_URL, private_token=GITLAB_TOKEN, ssl_verify=False)
    PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID")
    project = gitlab_client.projects.get(PROJECT_ID)

    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
    auth = AppAuthToken(token=GITHUB_TOKEN)
    g = Github(auth=auth)
    repo = g.get_user().get_repo('Uncoder_IO')  # repo name

    ssl_context = create_ssl_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    OS_LOG_HOST = os.environ.get("OS_LOG_HOST")
    OS_LOG_PORT = os.environ.get("OS_LOG_PORT")
    OS_LOG_USER = os.environ.get("OS_LOG_USER")
    OS_LOG_PASS = os.environ.get("OS_LOG_PASS")
    os_log_client = OpenSearch(
        hosts=[{'host': OS_LOG_HOST, 'port': OS_LOG_PORT}],
        http_compress=True,
        scheme="https",
        http_auth=(OS_LOG_USER, OS_LOG_PASS),
        verify_certs=False
    )
    GitLabSyncCommitGitHub.init(using=os_log_client)

    def __get_saved_commits_info(self, branch_name: str):
        try:
            query = {
              "query": {
                "bool": {
                  "must": [
                    {
                      "term": {
                        "gitlab.branch": {
                          "value": branch_name
                        }
                      }
                    }
                  ]
                }
              }
            }
            saved_commits_search = self.os_log_client.search(index=INDEX_NAME, body=query)
            hits = saved_commits_search.get("hits", {}).get("hits", [])
            return [
                doc.get("_source", {}).get("gitlab", {}).get("commit_sha")
                for doc in hits
            ]
        except Exception as err:
            raise Exception("Couldn't get saved branch commits")

    def __push_commits_info_to_opensearch(self, github: dict, gitlab: dict):
        doc = GitLabSyncCommitGitHub(github=github, gitlab=gitlab, created=datetime.datetime.now())
        response = doc.save(using=self.os_log_client)
        if response == "created":
            return
        raise Exception(f"Pushed commits sha not saved! Status: {response}")

    @staticmethod
    def __prepare_diff(diff: list):
        for el in diff:
            el_path = el.get("new_path")
            file_name = basename(el_path)
            file_path = join(dirname(__file__), el_path)
            yield {
                "name": file_name,
                "project_path": f"translator/{el_path}",
                "path": file_path,
                "code": el.get("b_mode"),
                "type": "blob"
            }

    def prepare_gitlab_commit_info(self, commit) -> dict:
        return {
            "author": commit.committer_name,
            "sha": commit.id,
            "commit_message": commit.message,
            "commit_title": commit.title,
            "changes": self.__prepare_diff(commit.diff())
        }

    def __get_gitlab_branch_from_commit(self, commit):
        list_branches = commit.refs()
        try:
            return list_branches[0].get("name")
        except (KeyError, AttributeError):
            return

    def __get_gitlab_commits(self, commit_sha: str):
        origin_commit = self.project.commits.get(commit_sha)
        branch = self.__get_gitlab_branch_from_commit(commit=origin_commit)
        saved_commits = self.__get_saved_commits_info(branch_name=branch)
        search_parent = True
        parent_ids = origin_commit.parent_ids
        parent_commits = []
        while search_parent:
            for parent_commit_sha in parent_ids:
                parent_commit = self.project.commits.get(parent_commit_sha)
                parent_commit_branch = self.__get_gitlab_branch_from_commit(commit=parent_commit)
                if branch == parent_commit_branch and parent_commit.id not in saved_commits:
                    parent_commits.append(parent_commit)
                    parent_ids.extend(parent_commit.parent_ids)
                else:
                    search_parent = False
                    break
        reversed_parent_commits = list(reversed(parent_commits))
        reversed_parent_commits.append(origin_commit)
        return {
            "branch": branch,
            "commits": [self.prepare_gitlab_commit_info(commit=c) for c in reversed_parent_commits]
        }

    def create_new_github_branch(self, branch_name: str):
        main_branch_ref = self.repo.get_git_ref('heads/main')
        main_sha = main_branch_ref.object.sha
        return self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_sha)

    def checkout_github_branch(self, branch: str):
        try:
            return self.repo.get_git_ref(f'heads/{branch}')
        except UnknownObjectException as err:
            print("Branch not exist. Creating new one...")
            return self.create_new_github_branch(branch_name=branch)

    def push_files_to_github(self, payload: dict, gitlab_branch: str):
        branch_ref = self.checkout_github_branch(branch=gitlab_branch)
        branch_sha = branch_ref.object.sha
        base_tree = self.repo.get_git_tree(branch_sha)

        element_list = list()
        for file in payload.get("changes", []):
            with open(file.get("path")) as input_file:
                data = input_file.read()
            element = InputGitTreeElement(
                path=file.get("project_path"),
                mode=file.get("code"),
                type=file.get("type"),
                content=data
            )
            element_list.append(element)

        tree = self.repo.create_git_tree(element_list, base_tree)
        parent = self.repo.get_git_commit(branch_sha)
        commit = self.repo.create_git_commit(
            message=payload.get("commit_message"),
            tree=tree,
            parents=[parent])
        branch_ref.edit(commit.sha)
        self.__push_commits_info_to_opensearch(
            gitlab={"branch": gitlab_branch, "commit_sha": payload.get("sha")},
            github={"branch": gitlab_branch, "commit_sha": commit.sha}
        )

    def run(self, commit_sha: str):
        gitlab_commits_info = self.__get_gitlab_commits(commit_sha=commit_sha)
        for gitlab_commit_info in gitlab_commits_info.get("commits", []):
            self.push_files_to_github(payload=gitlab_commit_info, gitlab_branch=gitlab_commits_info.get("branch"))


if __name__ == "__main__":
    revision_number = 'a47be51cca70b9f397935fbf0ccd6e906620a9b4'
    GitLabToGitHubSync().run(commit_sha=revision_number)

